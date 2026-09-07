# Optima Delivery Pickup

Core multi-proveedor para puntos de recogida en Odoo 18.

## Responsabilidades

- Campos físicos de producto: Largo, Ancho y Alto (mm).
- Opción genérica "Punto de recogida" en el checkout.
- Estado genérico del punto seleccionado en `sale.order`.
- Reutiliza `sale.order.pickup_location_data` estándar de Odoo para la dirección logística final.
- Registro frontend de proveedores para que cada adaptador aporte su selector/mapa.
- No depende de Sendcloud, UPS, GLS, CTT ni ningún carrier concreto.

## V0.2

El pago se mantiene bloqueado al usar la opción pickup hasta implementar:

- validación de peso + dimensiones;
- resolución del método real;
- precio real o tarifa Odoo;
- asignación de `carrier_id`.
