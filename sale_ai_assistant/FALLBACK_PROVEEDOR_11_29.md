# Versión 11.29 — proveedor principal y respaldo en Vercel

En **Ventas → Asistente IA → Modelos IA → modelo individual → Enrutamiento Vercel por modelo**:

1. Selecciona **Proveedor específico**.
2. Introduce el **slug del proveedor principal** que aparezca en el catálogo de Vercel.
3. Si quieres respaldo, indica el **slug del proveedor Vercel de respaldo**; debe ofrecer el **mismo modelo**. No es un modelo alternativo.

Cuando hay dos proveedores, la llamada a Chat Completions incluye:

```json
{
  "providerOptions": {
    "gateway": {
      "order": ["principal", "respaldo"],
      "only": ["principal", "respaldo"]
    }
  }
}
```

`order` indica a Vercel que intente primero el principal; `only` impide utilizar un tercero cuando ambos fallan. Si no hay respaldo, se conserva el comportamiento anterior: `only: ["principal"]`. La selección automática, por coste, por latencia y por throughput no cambia.

El enrutamiento se configura por **modelo individual**, también dentro de perfiles multimodelo, e incluye las llamadas a herramientas y a los modelos de visión. El proveedor final y los costes reales siguen obteniéndose mediante el registro de consumo y su consulta **manual**, sin `ir.cron`.

El respaldo interviene cuando Vercel considera que debe hacer failover (caída, error o indisponibilidad), no cuando la calidad de la respuesta simplemente no satisface al usuario. Una petición que falle a nivel de Odoo o de red antes de llegar a Vercel no garantiza que este mecanismo se active.

**Compatibilidad:** al actualizar desde 11.26 o 11.28, el respaldo estará inicialmente vacío. Los modelos configurados con proveedor fijo seguirán usando exclusivamente el principal hasta que configures un segundo. Se conservan todas las demás funcionalidades.

**Pruebas:** se verificó el payload con HTTP simulado, el rechazo de configuraciones inválidas y el enrutamiento antiguo. Falta una prueba real con proveedores de tu cuenta.
