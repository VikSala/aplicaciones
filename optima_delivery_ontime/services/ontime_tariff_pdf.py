import io
import re


SERVICE_ECONOMY = "economy_24_48"
SERVICE_XS24 = "xs_24"

ZONE_PROVINCIAL = "PROVINCIAL"
ZONE_REGIONAL = "REGIONAL"
ZONE_IBERIA = "IBERIA"
ZONE_CEUTA = "CEUTA"
ZONE_MELILLA = "MELILLA"
ZONE_BALEARES_MAYORES = "BALEARES_MAYORES"
ZONE_BALEARES_MENORES = "BALEARES_MENORES"
ZONE_CANARIAS_MAYORES = "CANARIAS_MAYORES"
ZONE_CANARIAS_MENORES = "CANARIAS_MENORES"


class OnTimeTariffPDFError(ValueError):
    pass


class OnTimeTariffPDFParser:
    """Parse the official OnTime XS tariff sheet.

    The parser is deliberately strict. It supports the matrix layout used by
    the official "TARIFAS PAQUETERÍA XS" sheet and fails instead of silently
    importing incorrect prices if the layout changes.
    """

    _PRICE_TOKEN_RE = re.compile(r"(?:(-)|([0-9]+(?:\.[0-9]{3})*,[0-9]{2}))\s*€")
    _WEIGHT_ROW_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s+(.*)$")
    _YEAR_RE = re.compile(r"TARIFAS\s+PAQUETER[IÍ]A\s+XS\s+(20\d{2})", re.IGNORECASE)

    def __init__(self, payload):
        self.payload = payload

    @staticmethod
    def _load_pdf_reader(payload):
        try:
            from pypdf import PdfReader
        except ImportError:
            try:
                from PyPDF2 import PdfReader
            except ImportError as exc:
                raise OnTimeTariffPDFError(
                    "La importación de tarifas PDF requiere el paquete Python 'pypdf' "
                    "(o 'PyPDF2') en el servidor de Odoo."
                ) from exc
        try:
            return PdfReader(io.BytesIO(payload))
        except Exception as exc:
            raise OnTimeTariffPDFError("No se ha podido abrir el PDF de tarifas OnTime.") from exc

    def _extract_text(self):
        reader = self._load_pdf_reader(self.payload)
        if getattr(reader, "is_encrypted", False):
            try:
                reader.decrypt("")
            except Exception as exc:
                raise OnTimeTariffPDFError("El PDF de tarifas OnTime está protegido y no puede leerse.") from exc
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        if not text.strip():
            raise OnTimeTariffPDFError(
                "El PDF no contiene texto extraíble. Usa el PDF original de OnTime, no una imagen escaneada."
            )
        return text

    @classmethod
    def _prices_from_text(cls, text):
        values = []
        for match in cls._PRICE_TOKEN_RE.finditer(text or ""):
            if match.group(1):
                values.append(None)
            else:
                values.append(float(match.group(2).replace(".", "").replace(",", ".")))
        return values

    @staticmethod
    def _weight(value):
        return float(str(value).replace(",", "."))

    @classmethod
    def _split_blocks(cls, text):
        blocks = []
        current_rows = []
        for raw_line in text.splitlines():
            line = " ".join(raw_line.strip().split())
            if not line:
                continue

            if re.match(r"^Kg\s+Adicional\b", line, re.IGNORECASE):
                extra = cls._prices_from_text(line)
                if current_rows and extra:
                    blocks.append({"rows": current_rows, "extra": extra})
                    current_rows = []
                continue

            match = cls._WEIGHT_ROW_RE.match(line)
            if not match:
                continue
            values = cls._prices_from_text(match.group(2))
            if values:
                current_rows.append((cls._weight(match.group(1)), values))

        return blocks

    @staticmethod
    def _find_expected_blocks(blocks):
        # Official sheet order:
        #  1) XS 10h + XS Express 12h + XS Economy 24-48h (9 columns)
        #  2) XS 24h mainland/special destinations (8 columns)
        #  3) XS Islands: Express + Economy (8 columns)
        #  4) XS 24h islands (4 columns)
        shapes = []
        for block in blocks:
            row_lengths = {len(values) for _weight, values in block["rows"]}
            extra_len = len(block["extra"])
            if len(row_lengths) == 1:
                shapes.append((next(iter(row_lengths)), extra_len, block))

        ordered = []
        expected = [9, 8, 8, 4]
        start = 0
        for column_count in expected:
            found = None
            for index in range(start, len(shapes)):
                row_len, extra_len, block = shapes[index]
                if row_len == column_count and extra_len == column_count:
                    found = (index, block)
                    break
            if not found:
                raise OnTimeTariffPDFError(
                    "No se reconoce la estructura del contrato OnTime. "
                    "Se esperaba la matriz oficial XS con bloques 9/8/8/4 columnas."
                )
            start = found[0] + 1
            ordered.append(found[1])
        return ordered

    @staticmethod
    def _append_zone_rates(result, block, service, zone_to_column):
        for zone, column in zone_to_column.items():
            if column >= len(block["extra"]):
                raise OnTimeTariffPDFError("La tabla OnTime tiene menos columnas de las esperadas.")
            extra_price = block["extra"][column]
            rows = []
            for weight, values in block["rows"]:
                if column >= len(values):
                    raise OnTimeTariffPDFError("Una fila del PDF OnTime está incompleta.")
                price = values[column]
                if price is not None:
                    rows.append(
                        {
                            "service": service,
                            "zone": zone,
                            "weight_to": weight,
                            "price": price,
                            "extra_kg_price": extra_price or 0.0,
                        }
                    )
            if rows:
                result.extend(rows)

    def parse(self):
        text = self._extract_text()
        year_match = self._YEAR_RE.search(text)
        year = int(year_match.group(1)) if year_match else False
        blocks = self._find_expected_blocks(self._split_blocks(text))
        top, xs24_main, islands_mix, xs24_islands = blocks

        rates = []
        self._append_zone_rates(
            rates,
            top,
            SERVICE_ECONOMY,
            {
                ZONE_PROVINCIAL: 6,
                ZONE_REGIONAL: 7,
                ZONE_IBERIA: 8,
            },
        )
        self._append_zone_rates(
            rates,
            xs24_main,
            SERVICE_XS24,
            {
                ZONE_PROVINCIAL: 0,
                ZONE_REGIONAL: 1,
                ZONE_IBERIA: 2,
                ZONE_CEUTA: 3,
                ZONE_MELILLA: 4,
            },
        )
        self._append_zone_rates(
            rates,
            islands_mix,
            SERVICE_ECONOMY,
            {
                ZONE_BALEARES_MAYORES: 4,
                ZONE_BALEARES_MENORES: 5,
                ZONE_CANARIAS_MAYORES: 6,
                ZONE_CANARIAS_MENORES: 7,
            },
        )
        self._append_zone_rates(
            rates,
            xs24_islands,
            SERVICE_XS24,
            {
                ZONE_BALEARES_MAYORES: 0,
                ZONE_BALEARES_MENORES: 1,
                ZONE_CANARIAS_MAYORES: 2,
                ZONE_CANARIAS_MENORES: 3,
            },
        )

        required_economy = {
            ZONE_PROVINCIAL,
            ZONE_REGIONAL,
            ZONE_IBERIA,
            ZONE_BALEARES_MAYORES,
            ZONE_BALEARES_MENORES,
            ZONE_CANARIAS_MAYORES,
            ZONE_CANARIAS_MENORES,
        }
        required_xs24 = {
            ZONE_PROVINCIAL,
            ZONE_REGIONAL,
            ZONE_IBERIA,
            ZONE_CEUTA,
            ZONE_MELILLA,
            ZONE_BALEARES_MAYORES,
            ZONE_BALEARES_MENORES,
            ZONE_CANARIAS_MAYORES,
            ZONE_CANARIAS_MENORES,
        }
        economy_zones = {rate["zone"] for rate in rates if rate["service"] == SERVICE_ECONOMY}
        xs24_zones = {rate["zone"] for rate in rates if rate["service"] == SERVICE_XS24}
        if not required_economy.issubset(economy_zones) or not required_xs24.issubset(xs24_zones):
            raise OnTimeTariffPDFError(
                "El PDF no contiene todas las zonas esperadas de XS ECONOMY 24-48h y XS 24h."
            )

        return {
            "year": year,
            "rates": rates,
            "text": text,
        }
