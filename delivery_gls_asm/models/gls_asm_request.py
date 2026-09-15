# Copyright 2020 Tecnativa - David Vidal
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import base64
import binascii
import logging
import os
import xml.etree.ElementTree as ET

from odoo import _
from odoo.exceptions import UserError

from .gls_asm_master_data import GLS_PICKUP_ERROR_CODES, GLS_SHIPMENT_ERROR_CODES

_logger = logging.getLogger(__name__)

try:
    from suds.client import Client
    from suds.sax.text import Raw
    from suds.sudsobject import asdict
except (OSError, ImportError) as err:
    _logger.debug(err)


class GlsAsmRequest:
    """Interface between GLS-ASM SOAP API and Odoo recordset
    Abstract GLS-ASM API Operations to connect them with Odoo

    Not all the features are implemented, but could be easily extended with
    the provided API. We leave the operations empty for future.
    """

    def __init__(self, uidcustomer=None):
        """As the wsdl isn't public, we have to load it from local"""
        wsdl_path = os.path.join(
            os.path.dirname(os.path.realpath(__file__)), "../api/gls_asm_api.wsdl"
        )
        self.uidcustomer = uidcustomer or ""
        self.client = Client(f"file:{wsdl_path}", timeout=90)

    def _recursive_asdict(self, suds_object):
        """As suds response is an special object, we convert it into
        a more usable python dict. Taken form:
        https://stackoverflow.com/a/15678861
        """
        out = {}
        for k, v in asdict(suds_object).items():
            if hasattr(v, "__keylist__"):
                out[k] = self._recursive_asdict(v)
            elif isinstance(v, list):
                out[k] = []
                for item in v:
                    if hasattr(item, "__keylist__"):
                        out[k].append(self._recursive_asdict(item))
                    else:
                        out[k].append(item)
            else:
                out[k] = v
        return out

    def _prepare_cancel_shipment_docin(self, **kwargs):
        """ASM API is not very standard. Prepare parameters to pass them raw in
        the SOAP message"""
        return """
            <Servicios uidcliente="{uidcustomer}"
                       xmlns="http://www.asmred.com/">
                <Envio referencia="{referencia}" />
            </Servicios>
        """.format(**kwargs)

    def _prepare_cancel_pickup_docin(self, **kwargs):
        return """
            <Servicios uidcliente="{uidcustomer}"
                       xmlns="http://www.asmred.com/">
                <Recogida referencia="{referencia}" />
            </Servicios>
        """.format(**kwargs)

    def _prepare_send_shipping_docin(self, **kwargs):
        """ASM API is not very standard. Prepare parameters to pass them raw in
        the SOAP message"""
        return """
            <Servicios uidcliente="{uidcustomer}"
                       xmlns="http://www.asmred.com/">
                <Envio codbarras="">
                    <Fecha>{fecha}</Fecha>
                    <Portes>{portes}</Portes>
                    <Servicio>{servicio}</Servicio>
                    <Horario>{horario}</Horario>
                    <Bultos>{bultos}</Bultos>
                    <Peso>{peso}</Peso>
                    <Volumen>{volumen}</Volumen>
                    <Declarado>{declarado}</Declarado>
                    <DNINomb>{dninomb}</DNINomb>
                    <FechaPrevistaEntrega>{fechaentrega}</FechaPrevistaEntrega>
                    <Retorno>{retorno}</Retorno>
                    <Pod>{pod}</Pod>
                    <PODObligatorio>{podobligatorio}</PODObligatorio>
                    <Remite>
                        <Plaza>{remite_plaza}</Plaza>
                        <Nombre>{remite_nombre}</Nombre>
                        <Direccion>{remite_direccion}</Direccion>
                        <Poblacion>{remite_poblacion}</Poblacion>
                        <Provincia>{remite_provincia}</Provincia>
                        <Pais>{remite_pais}</Pais>
                        <CP>{remite_cp}</CP>
                        <Telefono>{remite_telefono}</Telefono>
                        <Movil>{remite_movil}</Movil>
                        <Email>{remite_email}</Email>
                        <Departamento>{remite_departamento}</Departamento>
                        <NIF>{remite_nif}</NIF>
                        <Observaciones>{remite_observaciones}</Observaciones>
                    </Remite>
                    <Destinatario>
                        <Codigo>{destinatario_codigo}</Codigo>
                        <Plaza>{destinatario_plaza}</Plaza>
                        <Nombre>{destinatario_nombre}</Nombre>
                        <Direccion>{destinatario_direccion}</Direccion>
                        <Poblacion>{destinatario_poblacion}</Poblacion>
                        <Provincia>{destinatario_provincia}</Provincia>
                        <Pais>{destinatario_pais}</Pais>
                        <CP>{destinatario_cp}</CP>
                        <Telefono>{destinatario_telefono}</Telefono>
                        <Movil>{destinatario_movil}</Movil>
                        <Email>{destinatario_email}</Email>
                        <Observaciones>
                            {destinatario_observaciones}
                        </Observaciones>
                        <ATT>{destinatario_att}</ATT>
                        <Departamento>{destinatario_departamento}</Departamento>
                        <NIF>{destinatario_nif}</NIF>
                    </Destinatario>
                    <Referencias>
                        <Referencia tipo="C">{referencia_c}</Referencia>
                        <Referencia tipo="0">{referencia_0}</Referencia>
                    </Referencias>
                    <Importes>
                        <Debidos>{importes_debido}</Debidos>
                        <Reembolso>{importes_reembolso}</Reembolso>
                    </Importes>
                    <Seguro tipo="{seguro}">
                        <Descripcion>{seguro_descripcion}</Descripcion>
                        <Importe>{seguro_importe}</Importe>
                    </Seguro>
                    <DevuelveAdicionales>
                        <PlazaDestino />
                        <Etiqueta tipo="{etiqueta}" />
                        <EtiquetaDevolucion tipo="{etiqueta_devolucion}" />
                    </DevuelveAdicionales>
                    <DevolverDatosASMDestino />
                    <Cliente>
                        <Codigo>{cliente_codigo}</Codigo>
                        <Plaza>{cliente_plaza}</Plaza>
                        <Agente>{cliente_agente}</Agente>
                    </Cliente>
                </Envio>
            </Servicios>
        """.format(**kwargs)

    def _prepare_send_pickup_docin(self, **kwargs):
        """ASM API is not very standard. Prepare parameters to pass them raw in
        the SOAP message"""
        return """
            <Servicios uidcliente="{uidcustomer}"
                       xmlns="http://www.asmred.com/">
                <Recogida codrecogida="">
                    <Horarios>
                        <Fecha dia="{fecha}">
                            <Horario desde="09:00" hasta="18:00" />
                        </Fecha>
                    </Horarios>
                    <RecogerEn>
                        <Nombre>{remite_nombre}</Nombre>
                        <Direccion>{remite_direccion}</Direccion>
                        <Poblacion>{remite_poblacion}</Poblacion>
                        <Provincia>{remite_provincia}</Provincia>
                        <Pais>{remite_pais}</Pais>
                        <CP>{remite_cp}</CP>
                        <Telefono>{remite_telefono}</Telefono>
                        <Movil>{remite_movil}</Movil>
                        <Email>{remite_email}</Email>
                        <Contacto></Contacto>
                    </RecogerEn>
                    <Entregas>
                        <Envio>
                            <FechaPrevistaEntrega>{fechaentrega}</FechaPrevistaEntrega>
                            <Portes>{portes}</Portes>
                            <Servicio>{servicio}</Servicio>
                            <Horario>{horario}</Horario>
                            <Bultos>{bultos}</Bultos>
                            <Peso>{peso}</Peso>
                            <Destinatario>
                                <Nombre>{destinatario_nombre}</Nombre>
                                <Direccion>{destinatario_direccion}</Direccion>
                                <Poblacion>{destinatario_poblacion}</Poblacion>
                                <Provincia>{destinatario_provincia}</Provincia>
                                <Pais>{destinatario_pais}</Pais>
                                <CP>{destinatario_cp}</CP>
                                <Telefono>{destinatario_telefono}</Telefono>
                                <Movil>{destinatario_movil}</Movil>
                                <Email>{destinatario_email}</Email>
                                <Observaciones>{observaciones}</Observaciones>
                            </Destinatario>
                        </Envio>
                    </Entregas>
                    <Referencias>
                        <Referencia tipo="C">{referencia_c}</Referencia>
                        <Referencia tipo="A">{referencia_a}</Referencia>
                    </Referencias>
                </Recogida>
            </Servicios>
        """.format(**kwargs)

    def _send_shipping(self, vals):
        """Create new shipment
        :params vals dict of needed values
        :returns dict with GLS response containing the shipping codes, labels,
        an other relevant data
        """
        vals.update({"uidcustomer": self.uidcustomer})
        xml = Raw(self._prepare_send_shipping_docin(**vals))
        _logger.debug(xml)
        try:
            res = self.client.service.GrabaServicios(docIn=xml)
        except Exception as e:
            raise UserError(
                _(
                    "No response from server recording GLS delivery %(ref)s.\n"
                    "Traceback:\n%(error)s"
                )
                % {"ref": vals.get("referencia_c", ""), "error": e}
            ) from e
        # Convert result suds object to dict and set the root conveniently
        # GLS API Errors have codes below 0 so we have to
        # convert to int as well
        res = self._recursive_asdict(res)["Servicios"]["Envio"]
        res["gls_sent_xml"] = xml
        _logger.debug(res)
        res["_return"] = int(res["Resultado"]["_return"])
        if res["_return"] < 0:
            raise UserError(
                _(
                    "GLS returned an error trying to record the shipping for %(ref)s.\n"
                    "Error:\n%(error)s"
                )
                % {
                    "ref": vals.get("referencia_c", ""),
                    "error": GLS_SHIPMENT_ERROR_CODES.get(
                        res["_return"], res["_return"]
                    ),
                }
            )
        if res.get("Etiquetas", {}).get("Etiqueta", {}).get("value"):
            res["gls_label"] = binascii.a2b_base64(
                res["Etiquetas"]["Etiqueta"]["value"]
            )
        return res

    def _send_pickup(self, vals):
        """Create new pickup
        :params vals dict of needed values
        :returns dict with GLS response containing the shipping codes, labels,
        an other relevant data
        """
        vals.update({"uidcustomer": self.uidcustomer})
        xml = Raw(self._prepare_send_pickup_docin(**vals))
        _logger.debug(xml)
        try:
            res = self.client.service.GrabaServicios(docIn=xml)
        except Exception as e:
            raise UserError(
                _(
                    "No response from server recording GLS delivery %(ref)s.\n"
                    "Traceback:\n%(error)s"
                )
                % {"ref": vals.get("referencia_c", ""), "error": e}
            ) from e
        # Convert result suds object to dict and set the root conveniently
        # GLS API Errors have codes below 0 so we have to
        # convert to int as well
        res = self._recursive_asdict(res)["Servicios"]["Recogida"]
        res["gls_sent_xml"] = xml
        _logger.debug(res)
        res["_return"] = int(res["Resultado"]["_return"])
        if res["_return"] < 0:
            raise UserError(
                _(
                    "GLS returned an error trying to record the shipping for %(ref)s.\n"
                    "Error:\n%(error)s"
                )
                % {
                    "ref": vals.get("referencia_c", ""),
                    "error": GLS_PICKUP_ERROR_CODES.get(res["_return"], res["_return"]),
                }
            )
        return res

    def _get_delivery_info(self, reference=False):
        """Get delivery info recorded in GLS for the given reference
        :param str reference -- GLS tracking number
        :returns: shipping info dict
        """
        try:
            res = self.client.service.GetExpCli(codigo=reference, uid=self.uidcustomer)
            _logger.debug(res)
        except Exception as e:
            raise UserError(
                _(
                    "GLS: No response from server getting state from ref %(ref)s.\n"
                    "Traceback:\n%(error)s"
                )
                % {"ref": reference, "error": e}
            ) from e
        res = self._recursive_asdict(res)
        return res

    def _get_pickup_info(self, reference=False):
        xml = Raw(
            f"""
            <Servicios uidcliente="{self.uidcustomer}" xmlns="http://www.asmred.com/">
                <Recogida codrecogida="{reference}" />
            </Servicios>
        """
        )
        res = self.client.service.Tracking(docIn=xml)
        _logger.debug(res)
        return self._recursive_asdict(res)

    def _get_tracking_states(self, reference=False):
        """Get just tracking states from GLS info for the given reference
        :param str reference -- GLS tracking number
        :returns: list of tracking states
        """
        res = self._get_delivery_info(reference)
        res = (res.get("expediciones") or {}).get("exp", {})
        return res

    def _get_pickup_tracking_states(self, reference=False):
        res = self._get_pickup_info(reference)
        res = (
            res.get("Servicios", {})
            .get("Recogida", {})
            .get("Tracking", {})
            .get("TrackingCliente", {})
        )
        # If there's just one state, we'll get a single dict, otherwise we
        # get a list of dicts
        if isinstance(res, dict):
            return [res]
        return res

    @staticmethod
    def _decode_pdf_candidate(value):
        """Return PDF bytes when *value* contains raw/base64 PDF data."""
        if value in (None, False, ""):
            return False
        if isinstance(value, bytearray):
            value = bytes(value)
        if isinstance(value, bytes):
            raw = value.strip()
            if raw.startswith(b"%PDF"):
                return raw
            try:
                decoded = base64.b64decode(raw, validate=False)
            except (binascii.Error, ValueError):
                return False
            return decoded if decoded.startswith(b"%PDF") else False
        if not isinstance(value, str):
            return False
        text = value.strip()
        if not text:
            return False
        if text.startswith("%PDF"):
            return text.encode("latin1", errors="ignore")
        # EtiquetaEnvioV2 is declared as xsd:any and can therefore arrive as
        # an XML fragment containing the actual base64 payload.
        if text.startswith("<"):
            try:
                root = ET.fromstring(text)
            except ET.ParseError:
                root = None
            if root is not None:
                for element in root.iter():
                    if element.text:
                        pdf = GlsAsmRequest._decode_pdf_candidate(element.text)
                        if pdf:
                            return pdf
        compact = "".join(text.split())
        try:
            decoded = base64.b64decode(compact, validate=False)
        except (binascii.Error, ValueError):
            return False
        return decoded if decoded.startswith(b"%PDF") else False

    def _extract_pdf_from_label_response(self, value, _seen=None):
        """Extract a PDF from the heterogeneous Suds/XML GLS response.

        ``EtiquetaEnvioV2Result`` is ``xsd:any`` in the current GLS WSDL, so
        Suds may expose the payload as a dict, list, XML element/string or a
        nested ``value``/``base64Binary`` member depending on the response.
        """
        if _seen is None:
            _seen = set()
        marker = id(value)
        if marker in _seen:
            return False
        _seen.add(marker)

        pdf = self._decode_pdf_candidate(value)
        if pdf:
            return pdf

        if isinstance(value, dict):
            preferred = []
            others = []
            for key, item in value.items():
                key_text = str(key).lower()
                if any(token in key_text for token in ("base64", "etiqueta", "label", "value", "any")):
                    preferred.append(item)
                else:
                    others.append(item)
            for item in preferred + others:
                pdf = self._extract_pdf_from_label_response(item, _seen)
                if pdf:
                    return pdf
            return False

        if isinstance(value, (list, tuple, set)):
            for item in value:
                pdf = self._extract_pdf_from_label_response(item, _seen)
                if pdf:
                    return pdf
            return False

        if hasattr(value, "__keylist__"):
            try:
                return self._extract_pdf_from_label_response(
                    self._recursive_asdict(value), _seen
                )
            except Exception:
                pass

        # Suds xsd:any values may be sax Elements. Their string form contains
        # the XML fragment, which the decoder above knows how to inspect.
        try:
            text = str(value)
        except Exception:
            return False
        if text and text != object.__repr__(value):
            return self._decode_pdf_candidate(text)
        return False

    def _shipping_label(self, reference=False):
        """Get the PDF shipping label for a GLS shipment barcode.

        Prefer ``EtiquetaEnvioV2`` as documented by the current GLS service.
        Its result is XML (xsd:any), so parse the nested payload instead of
        assuming a top-level ``base64Binary`` member.  If V2 returns no usable
        PDF, fall back to the still-published typed ``EtiquetaEnvio`` operation.
        """
        try:
            res = self.client.service.EtiquetaEnvioV2(
                uidCliente=self.uidcustomer,
                codigo=reference,
                tipoEtiqueta="PDF",
                plataforma="",
            )
            _logger.debug("GLS EtiquetaEnvioV2 response for %s: %r", reference, res)
        except Exception as e:
            raise UserError(
                _(
                    "GLS: No response from server printing label with ref %(ref)s.\n"
                    "Traceback:\n%(error)s"
                )
                % {"ref": reference, "error": e}
            ) from e

        pdf = self._extract_pdf_from_label_response(res)
        if pdf:
            return pdf

        _logger.warning(
            "GLS EtiquetaEnvioV2 returned no usable PDF for barcode %s; "
            "trying EtiquetaEnvio fallback",
            reference,
        )
        try:
            legacy_res = self.client.service.EtiquetaEnvio(
                uidCliente=self.uidcustomer,
                codigo=reference,
                tipoEtiqueta="PDF",
                plataforma="",
            )
            _logger.debug("GLS EtiquetaEnvio response for %s: %r", reference, legacy_res)
        except Exception as e:
            _logger.warning(
                "GLS EtiquetaEnvio fallback failed for barcode %s: %s", reference, e
            )
            return False
        return self._extract_pdf_from_label_response(legacy_res)

    def _cancel_shipment(self, reference=False):
        """Cancel shipment for a given reference
        :param str reference -- shipping reference to cancel
        :returns: dict -- result of operation with format
        {
            'value': str - response message,
            '_return': int  - response status
        }
        Possible response values:
             0 -> Expedición anulada
            -1 -> No existe envío
            -2 -> Tiene tracking operativo
        """
        xml = Raw(
            self._prepare_cancel_shipment_docin(
                uidcustomer=self.uidcustomer, referencia=reference
            )
        )
        _logger.debug(xml)
        try:
            response = self.client.service.Anula(docIn=xml)
            _logger.debug(response)
        except Exception as e:
            _logger.error(
                f"No response from server canceling GLS ref {reference}.\n"
                f"Traceback:\n{e}"
            )
            return {}
        response = self._recursive_asdict(response.Servicios.Envio.Resultado)
        response["gls_sent_xml"] = xml
        response["_return"] = int(response["_return"])
        return response

    def _cancel_pickup(self, reference=False):
        """Cancel shipment for a given reference
        :param str reference -- shipping reference to cancel
        :returns: dict -- result of operation with format
        {
            'value': str - response message,
            '_return': int  - response status
        }
        Possible response values:
             0 -> Recogida anulada
            -1 -> No existe recogida
            -2 -> Tiene tracking operativo
        """
        xml = Raw(
            self._prepare_cancel_pickup_docin(
                uidcustomer=self.uidcustomer, referencia=reference
            )
        )
        _logger.debug(xml)
        try:
            response = self.client.service.Anula(docIn=xml)
            _logger.debug(response)
        except Exception as e:
            _logger.error(
                f"No response from server canceling GLS ref {reference}.\n"
                f"Traceback:\n{e}"
            )
            return {}
        response = self._recursive_asdict(response.Servicios.Recogida.Resultado)
        response["gls_sent_xml"] = xml
        response["_return"] = int(response["_return"])
        return response
