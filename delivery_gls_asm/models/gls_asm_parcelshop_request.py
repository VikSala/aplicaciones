# Copyright 2026
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import logging
from xml.etree import ElementTree as ET

import requests

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class GlsAsmParcelShopRequest:
    """Small client for the GLS Spain ParcelShop locator service.

    GLS documents ``GetParcelShopProximosV3`` in ``infoasm.asmx`` for locating
    ParcelShops from an address, town or postal code.  This service is separate
    from the b2b shipment API used by :class:`GlsAsmRequest` and does not require
    the GLS customer UID.
    """

    ENDPOINT = "https://ws-customer.gls-spain.es/infoasm.asmx"
    SOAP_ACTION = "http://www.asmred.com/GetParcelShopProximosV3"
    SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
    ASM_NS = "http://www.asmred.com/"

    def __init__(self, timeout=30):
        self.timeout = timeout

    @staticmethod
    def _local_name(tag):
        return tag.rsplit("}", 1)[-1] if "}" in tag else tag

    @classmethod
    def _child_text(cls, node, name):
        for child in list(node):
            if cls._local_name(child.tag).lower() == name.lower():
                return (child.text or "").strip()
        return ""

    @staticmethod
    def _to_float(value):
        if value in (None, ""):
            return False
        try:
            return float(str(value).strip().replace(",", "."))
        except (TypeError, ValueError):
            return False

    def _build_request(self, direccion, redes="1", pais="ES"):
        envelope = ET.Element(ET.QName(self.SOAP_NS, "Envelope"))
        body = ET.SubElement(envelope, ET.QName(self.SOAP_NS, "Body"))
        operation = ET.SubElement(
            body, ET.QName(self.ASM_NS, "GetParcelShopProximosV3")
        )
        ET.SubElement(operation, ET.QName(self.ASM_NS, "direccion")).text = direccion
        ET.SubElement(operation, ET.QName(self.ASM_NS, "redes")).text = redes or "1"
        ET.SubElement(operation, ET.QName(self.ASM_NS, "pais")).text = pais or "ES"
        return ET.tostring(envelope, encoding="utf-8", xml_declaration=True)

    def _raise_soap_fault(self, root):
        for node in root.iter():
            if self._local_name(node.tag) != "Fault":
                continue
            message = ""
            for subnode in node.iter():
                if self._local_name(subnode.tag) in ("faultstring", "Text"):
                    message = (subnode.text or "").strip()
                    if message:
                        break
            raise UserError(
                _("GLS ParcelShop service returned an error: %(error)s")
                % {"error": message or _("Unknown SOAP fault")}
            )

    def _extract_result_root(self, root):
        result = None
        for node in root.iter():
            if self._local_name(node.tag) == "GetParcelShopProximosV3Result":
                result = node
                break
        if result is None:
            return root

        # Normal GLS response: the XML result is embedded directly as child
        # elements because the WSDL declares it as xsd:any.
        if list(result):
            return result

        # Be defensive in case a proxy/server serialises the inner XML as text.
        text = (result.text or "").strip()
        if text.startswith("<"):
            try:
                return ET.fromstring(text)
            except ET.ParseError:
                _logger.warning("Unable to parse embedded GLS ParcelShop XML")
        return result

    def _parse_response(self, content):
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            raise UserError(
                _("GLS ParcelShop returned an invalid XML response: %(error)s")
                % {"error": exc}
            ) from exc

        self._raise_soap_fault(root)
        result_root = self._extract_result_root(root)

        shops = []
        for node in result_root.iter():
            if self._local_name(node.tag) != "ParcelShop":
                continue
            shops.append(
                {
                    "network_id": self._child_text(node, "IdRed"),
                    "code": self._child_text(node, "Codigo"),
                    "name": self._child_text(node, "Nombre"),
                    "address": self._child_text(node, "Direccion"),
                    "city": self._child_text(node, "Poblacion"),
                    "postal_code": self._child_text(node, "CodigoPostal"),
                    "country_code": self._child_text(node, "Pais"),
                    "latitude": self._to_float(self._child_text(node, "Latitud")),
                    "longitude": self._to_float(self._child_text(node, "Longitud")),
                    "monday_hours": self._child_text(node, "HorarioLunes"),
                    "tuesday_hours": self._child_text(node, "HorarioMartes"),
                    "wednesday_hours": self._child_text(node, "HorarioMiercoles"),
                    "thursday_hours": self._child_text(node, "HorarioJueves"),
                    "friday_hours": self._child_text(node, "HorarioViernes"),
                    "saturday_hours": self._child_text(node, "HorarioSabado"),
                    # GLS documentation does not state a unit for this value,
                    # so keep it exactly as returned by the service.
                    "distance": self._child_text(node, "Distancia"),
                }
            )
        return shops

    def search(self, direccion, redes="1", pais="ES"):
        direccion = (direccion or "").strip()
        redes = (redes or "1").strip()
        pais = (pais or "ES").strip().upper()
        if not direccion:
            raise UserError(_("A postal code or address is required."))
        if not pais:
            raise UserError(_("A country code is required."))

        payload = self._build_request(direccion, redes=redes, pais=pais)
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f'"{self.SOAP_ACTION}"',
            "User-Agent": "Odoo delivery_gls_asm",
        }
        try:
            response = requests.post(
                self.ENDPOINT,
                data=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise UserError(
                _(
                    "Unable to connect to the GLS ParcelShop service.\n"
                    "Error: %(error)s"
                )
                % {"error": exc}
            ) from exc

        _logger.debug("GLS ParcelShop response: %s", response.text)
        return self._parse_response(response.content)
