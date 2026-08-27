# Website Login Popup - Odoo 18

Módulo para Odoo 18 que mantiene el acceso y el registro dentro de la página actual mediante un popup.

## Incluye

- Login en popup sin abandonar la página actual.
- Colores de marca: verde `#00d27a`, azul `#0E273B` y hover `#23c979`.
- La pestaña **Registrarme** abre un selector con dos opciones: **Particular** y **Profesional**.
- Registro Particular: nombre, apellidos, correo, NIF, contraseña y confirmación. El NIF es obligatorio y se guarda en el contacto.
- Registro Profesional: los mismos campos más selector **Empresa / Autónomo**.
- Se han eliminado los checkboxes de comunicaciones comerciales, privacidad y aviso legal de ambos formularios.
- Al crear una cuenta profesional se asigna al contacto una etiqueta según el tipo elegido:
  - `Empresa` -> etiqueta **Empresa**.
  - `Autónomo` -> etiqueta **Autónomo**.
- Si la etiqueta ya existe se reutiliza; si no existe, se crea antes de asignarla.
- Los formularios de alta utilizan el flujo estándar `/web/signup` de Odoo.
- En caso de alta o login correcto, se recarga la página actual ya autenticada.


## 18.0.1.3.0
- Los profesionales de tipo Empresa se crean como contactos de tipo Compañía (`is_company=True`).
- La recuperación de contraseña se realiza dentro del popup y reutiliza `/web/reset_password`.
- El popup muestra el resultado del envío sin abandonar la página actual.


## Integración opcional con Login Attempt Security

Si está instalado `login_attempt_security`, el popup mantiene la autenticación estándar de Odoo y detecta cuando la cuenta queda temporalmente bloqueada. En ese caso muestra el tiempo restante de bloqueo dentro del propio popup.


## 18.0.1.5.0

- Marca con asterisco verde los campos obligatorios del registro.
- Apellidos pasa a ser opcional en Particular y Profesional.
- En Profesional, al elegir Empresa o Autónomo aparecen Calle y número, CP, Ciudad, NIF/CIF, Tlf/Móvil y Sitio Web.
- Para Empresa se muestra **CIF**; para Autónomo se muestra **NIF**. Ambos son obligatorios.
- Tlf/Móvil también es obligatorio. Calle y número, CP, Ciudad y Sitio Web son opcionales.
- Los datos profesionales se guardan en el contacto: `street`, `zip`, `city`, `vat`, `phone` y `website`.


## 18.0.1.6.0

- Particular: NIF obligatorio junto al correo y guardado en `res.partner.vat`.
- Profesional: Dirección se divide en Calle y número, CP y Ciudad.
- Empresa: CIF obligatorio. Autónomo: NIF obligatorio.
- Tlf/Móvil pasa a ser obligatorio.
- CP y Ciudad se guardan en `res.partner.zip` y `res.partner.city`.
