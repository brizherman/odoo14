# 🛒 Custom Purchase Flow — Resumen Ejecutivo
**Módulo:** `custom_purchase_flow` | **Versión:** 14.0.1.0.0 | **Fecha:** 6 de marzo de 2026

---

## ¿Qué es este módulo?

Este módulo **transforma por completo la manera en que compramos y surtimos nuestra tienda.** En lugar de depender de correos dispersos, aprobaciones de palabra y adivinar en qué parte del proceso va un pedido, cada orden de compra ahora recorre un **camino claro, controlado y paso a paso** — desde el momento en que alguien detecta que necesitamos producto, hasta que los anaqueles están surtidos.

Se acabó el "¿ya aprobaron el pedido?" Se acabó el "¿dónde está nuestra mercancía?" Se acabaron los faltantes en piso porque nadie estaba dándole seguimiento a la recepción.

**Un solo sistema. Todo el equipo en la misma página. Siempre.** 💪

---

---

## 🏆 Beneficios para el Negocio

### Para la Tienda 🏪
- **Mejor disponibilidad de producto** — los pedidos no se pierden entre departamentos
- **Recepción más rápida** — los recibos se crean antes de que llegue la mercancía
- **Sin sorpresas de desabasto** — cada orden se rastrea desde la aprobación hasta el anaquel

### Para Dirección 👔
- **Control total** — nada se compra sin aprobación explícita
- **Historial completo** — cada decisión, rechazo y transición queda registrada
- **Visibilidad en tiempo real** — el dashboard muestra toda la tubería de compras de un vistazo

### Para el Equipo de Compras 🛍️
- **Siguientes pasos claros** — cada etapa te dice exactamente qué hacer
- **Sin adivinar** — números de guía, fechas y estatus son campos estructurados, no notas en un chat
- **Menos idas y venidas** — los rechazos traen razones escritas, así las correcciones son inmediatas

### Para el Cajero 🧾
- **Confirmación simple** — un botón cuando llega la mercancía, eso es todo
- **El inventario ya está listo** — no hay que crear recibos a mano, ya están esperando

---

## 🗺️ El Recorrido Completo de una Orden de Compra

A continuación el ciclo de vida completo de cada orden, en el orden en que ocurre:

```
BORRADOR → POR APROBAR → APROBADA → ENVIADA A PROVEEDOR
    → PENDIENTE DE PAGO → PO SURTIENDO → PO EN TRÁNSITO
        → PO LLEGÓ → HECHO ✓
```

Cada etapa tiene un **responsable específico**, una **acción específica** y **cero ambigüedad** sobre qué sigue.

---

## 📋 Detalle de Cada Etapa

### 1. 📝 Borrador
- **¿Quién?** Coordinador
- **¿Qué pasa?** Se crea la solicitud de compra con todos los productos, cantidades y el proveedor deseado.
- **Acción clave:** Cuando está lista, el Coordinador presiona **"Solicitar Aprobación"** — la orden se bloquea para edición y avanza.
- **¿Por qué importa?** No hay órdenes a medias flotando por ahí. En el momento en que sale de esta etapa, es una solicitud real y comprometida.

---

### 2. ⏳ Por Aprobar
- **¿Quién?** Dirección
- **¿Qué pasa?** Dirección revisa la orden. Puede **aprobarla** o **rechazarla** con una razón escrita obligatoria.
- **Acción clave:** Aprobar → pasa a Aprobada. Rechazar → regresa a Borrador o se cancela, con la razón guardada permanentemente en el registro.
- **¿Por qué importa?** Dirección tiene visibilidad y control total. No se compra nada sin un visto bueno explícito. Cada rechazo queda documentado.

---

### 3. ✅ Aprobada
- **¿Quién?** Departamento de Compras
- **¿Qué pasa?** La orden está aprobada y lista para enviarse al proveedor.
- **Acción clave:** Compras contacta al proveedor y hace clic en **"Enviar a Proveedor"**.
- **¿Por qué importa?** Hay una entrega clara entre dirección y operaciones. Las órdenes aprobadas no se pierden en los correos.

---

### 4. 📧 Enviada a Proveedor
- **¿Quién?** Departamento de Compras
- **¿Qué pasa?** El proveedor tiene la orden. El sistema registra la **fecha y hora exacta** en que se envió.
- **Acciones clave:**
  - Marcar como **Pendiente de Pago** si hay que confirmar el pago antes de que surtan.
  - Marcar como **PO Surtiendo** una vez que el proveedor empieza a preparar el pedido (requiere capturar fecha de recepción primero).
- **¿Por qué importa?** Sabemos exactamente cuándo nos comprometimos con un proveedor. El reloj empieza a correr para la rendición de cuentas.

---

### 5. 💳 Pendiente de Pago
- **¿Quién?** Departamento de Compras
- **¿Qué pasa?** Se está procesando o confirmando el pago antes de que el proveedor envíe.
- **Acción clave:** Una vez confirmado el pago, se mueve a **PO Surtiendo**.
- **¿Por qué importa?** El flujo de caja está monitoreado. Nunca se pierde una orden porque el pago estaba pendiente y nadie lo estaba siguiendo.

---

### 6. 📦 PO Surtiendo
- **¿Quién?** Departamento de Compras
- **¿Qué pasa?** El proveedor está preparando y enviando el pedido activamente. El sistema crea automáticamente el **recibo de almacén** en este momento.
- **Acción clave:** Agregar número de guía (o documentar por qué no hay uno), luego mover a **PO En Tránsito**.
- **¿Por qué importa?** El recibo de inventario ya está creado y esperando. Cuando llega la mercancía, recibirla toma segundos.

---

### 7. 🚚 PO En Tránsito
- **¿Quién?** Departamento de Compras / Cajero
- **¿Qué pasa?** El pedido está físicamente en camino a la tienda. El número de guía está registrado.
- **Acción clave:** Cuando la mercancía llega físicamente, el Cajero confirma con **"PO Llegó"**.
- **¿Por qué importa?** Todos — compras, almacén, piso de venta — saben que viene producto y cuándo esperarlo. Sin sorpresas.

---

### 8. 📬 PO Llegó
- **¿Quién?** Cajero
- **¿Qué pasa?** La mercancía está físicamente en la tienda, confirmada por el Cajero.
- **Acción clave:** Una vez que se valida el recibo de inventario en almacén, se mueve a **Hecho**.
- **¿Por qué importa?** Hay una confirmación humana de que el producto está en mano. Nadie puede marcar algo como "terminado" sin que alguien haya verificado físicamente que llegó.

---

### 9. 🎉 Hecho ✓
- **¿Quién?** Departamento de Compras / Cajero
- **¿Qué pasa?** La orden está completamente cerrada. Los productos están recibidos, el recibo está validado, el ciclo cierra.
- **¿Por qué importa?** Historial limpio. Cada PO cerrada representa mercancía que llegó correctamente a la tienda.

---

## 👥 Roles y Responsabilidades

| Rol | ¿Qué hace? |
|---|---|
| **Coordinador** | Crea las órdenes de compra y las manda a aprobación |
| **Dirección** | Aprueba o rechaza órdenes con razones documentadas |
| **Departamento de Compras** | Gestiona todo el flujo desde aprobada hasta en tránsito |
| **Cajero** | Confirma la llegada física de la mercancía |

Cada rol ve únicamente las **acciones que le corresponden.** Sin confusión, sin pisarse entre áreas.

---

## ⚙️ Funcionalidades Clave que Hacen que Todo Funcione

### 🔢 Los Números de Guía Son Obligatorios
Antes de marcar una orden como "En Tránsito," el sistema **obliga** al usuario a ingresar un número de guía — o documentar explícitamente por qué no hay uno. Se acabaron los envíos perdidos.

### 📅 La Fecha de Recepción Es Obligatoria
Antes de marcar una orden como "Surtiendo," el sistema **requiere** una fecha estimada de recepción. Todo el equipo sabe cuándo esperar la entrega.

### 📝 Los Rechazos Quedan Documentados Para Siempre
Cada rechazo registra el motivo por escrito. Ya no hay "¿por qué rechazaron esto?" — la respuesta siempre está ahí mismo en la orden.

### 🔒 Las Órdenes No Se Pueden Borrar
Las órdenes de compra solo se pueden **cancelar** — nunca eliminar. Esto crea un historial completo y permanente de cada decisión de compra que hace el negocio, todo tiene un número consecutivo y ya no hay números brincados.

### 📊 Dashboard en Tiempo Real
El **Dashboard de Órdenes** muestra un conteo en vivo de las órdenes en cada etapa al mismo tiempo. De un vistazo, dirección puede ver cuántas órdenes esperan aprobación, cuántas están en tránsito y cuántas están pendientes de pago.

### ⏱️ Seguimiento Inteligente de Fechas
El sistema lleva automáticamente el registro de:
- Cuántos días lleva un borrador sin aprobarse (**Límite Pedir**)
- Cuántos días desde que se envió una orden al proveedor (**Límite Enviado**)
- La fecha estimada de recepción (**Límite Recepción**)


---

## 🚀 Resumen

El módulo `custom_purchase_flow` convierte las compras de un proceso fragmentado e informal en un **flujo de trabajo estructurado, accountable y de punta a punta.** Cada orden se rastrea. Cada decisión se documenta. Cada integrante del equipo sabe exactamente qué le toca hacer — y cuándo.

El resultado: una tienda que compra con más inteligencia, recibe más rápido y se mantiene bien surtida.

---

*Módulo: `custom_purchase_flow` | Odoo 14.0 | Última actualización: 6 de marzo de 2026*
