# Guía de uso — Control de precios mayoristas en POS

**Fecha:** 2026-10-29  
**Módulo:** Control de precios mayoristas en POS (`pos_wholesale_control` 14.0.1.1.0)

La caja elige sola si el ticket va a precio de menudeo o de mayoreo. El cajero no cambia la lista de precios. El módulo no cambia el tipo de cliente ni los pedidos ya cobrados.

---

## Qué hace

Con el control **activo** en la sucursal, al elegir un cliente la caja revisa dos cosas:

1. **Mes anterior.** Compras netas del mes calendario anterior. Si llegan al mínimo (por defecto **MXN $800**), el ticket completo va a mayoreo.
2. **Este pedido.** Si el mes anterior no alcanza, se suma el pedido actual **a precio de menudeo**, con descuentos e impuestos. Si llega al mínimo (por defecto **MXN $1,500**), este ticket va a mayoreo.

El total que se cobra puede quedar debajo de $1,500 después de aplicar mayoreo. El ticket sigue en mayoreo mientras el total a precio de menudeo siga en el mínimo, o mientras el mes anterior califique.

Si se quitan productos y ya no se cumple ninguna de las dos reglas, la caja vuelve a menudeo.

| Situación | Lista que usa la caja |
|---|---|
| Sin cliente | Menudeo (Lista de precios a Público en General) |
| No alcanza ningún mínimo | Menudeo |
| Califica y el tipo es Mayorista, Público General o Mayorista dormido | Lista de precios de Mayorista (Club Mayorista) |
| Califica y el tipo es Distribuidores | Super Precios a Distribuidores |

Los totales del historial suman **todas las sucursales**. La lista de precios es la de **esta caja**. Los meses se cuentan en hora de Tijuana. Una devolución resta el mes de la venta original, no el mes en que se devolvió.

Cuentan pedidos de punto de venta pagados o facturados y pedidos de venta confirmados. No cuentan borradores, cancelados ni pedidos sin pagar.

---

## Cómo configurarlo

Lo hace un usuario con **Administrador de mayoreo en POS** (los administradores de Odoo ya lo tienen). Se configura **por sucursal**, en **Punto de venta → Configuración → Ajustes**, bloque **Control de clientes mayoristas**.

Hágalo antes de encender el interruptor. Al instalar o actualizar, **Activar control de mayoreo** queda apagado.

1. **Lista de precios de menudeo:** Lista de precios a Público en General. Debe estar en MXN y disponible en cada caja de esa sucursal.
2. **Lista de precios de mayoreo:** Lista de precios de Mayorista. Misma moneda y también en cada caja.
3. **Asignaciones por tipo de cliente** (una sola fila activa por tipo):

| Tipo de cliente | Lista cuando califica |
|---|---|
| Mayorista | Lista de precios de Mayorista |
| Público General | Lista de precios de Mayorista |
| Mayorista dormido | Lista de precios de Mayorista |
| Distribuidores | Super Precios a Distribuidores |

4. Deje los mínimos en **800** y **1,500**, y la zona horaria en **America/Tijuana**, salvo una decisión distinta del negocio.
5. Confirme que cada caja use empleados de punto de venta (`pos_hr`). Quien autorice excepciones necesita el grupo **Punto de venta / Responsable** y un **NIP** de empleado.
6. Si aparece una advertencia amarilla, falta un tipo o una lista no está en alguna caja. Corríjalo antes de activar.
7. Encienda **Activar control de mayoreo** y guarde.

Mientras el interruptor está apagado, esa sucursal sigue vendiendo como antes.

---

## Cómo usarlo en la caja

El panel **Control de mayoreo** aparece arriba de las categorías, en el panel de productos, solo si la sucursal está activa. El cliente se elige con **Elegir cliente** en esa barra. El botón **Cliente** del pedido queda oculto mientras el control está activo en la pantalla de escritorio. En el celular, ese botón sigue en el pedido cuando el panel de productos no está a la vista. Recargue la caja con una actualización forzada del navegador después de un cambio de versión.

### Venta normal

1. Abra la sesión.
2. Elija el cliente. Sin cliente, el panel pide identificarlo y no muestra meses. El precio queda en menudeo.
3. Lea el panel: cliente, tipo, **Menudeo** o **Mayoreo**, lista activa, motivo y tres meses (el mes en curso dice **MTD**, mes a la fecha).
4. Agregue productos. La caja cambia la lista sola si el pedido cruza el mínimo. No use el botón de lista de precios: muestra **Lista de precios bloqueada**.
5. Cobrar. Antes de cerrar el ticket, el servidor vuelve a calcular. Si la lista no coincide, aparece *No se puede cobrar con la lista seleccionada* y regresa a los productos.

### Excepción de gerente

Sirve para un solo ticket: dar mayoreo aunque no califique, o dejar menudeo aunque sí califique. No cambia el tipo de cliente, su lista permanente ni el siguiente ticket.

1. En el panel, pulse **Excepción de gerente** (Manager override).
2. El gerente escribe su **NIP** y un **motivo**. Un NIP incorrecto o un motivo vacío no pasa.
3. El panel sigue mostrando la decisión automática y marca que hay excepción.
4. Si cambia el cliente, la excepción se borra y hay que autorizar de nuevo.

Si no hay conexión y no se puede leer el historial, el ticket se queda en menudeo y muestra el error. La única salida a mayoreo es esta excepción, y queda registrada.

---

## Dónde revisar después

- Pedido cobrado → pestaña **Mayoreo**: decisión automática, decisión final, motivo, montos y si hubo excepción.
- **Punto de venta → Excepciones de mayoreo**: quién autorizó, cajero, cliente, motivo y ticket. No se puede crear, editar ni borrar desde esa pantalla. La ven los gerentes de mayoreo.

---

## Preguntas frecuentes

**El total a pagar bajó al subir la cantidad.**  
El pedido cruzó MXN $1,500 a precio de menudeo y la caja pasó a mayoreo. El total cobrado puede quedar debajo de $1,500. Es correcto.

**El cliente compró mucho este mes y sigue en menudeo.**  
El mínimo de MXN $800 mira solo el **mes calendario anterior**. El mes en curso no cuenta para esa regla. Este mes solo ayuda si el pedido actual, a menudeo, llega a MXN $1,500.

**Compró en otra sucursal.**  
Sí cuenta. El historial suma todas las sucursales.

**¿$800.00 y $1,500.00 exactos califican?**  
Sí. MXN $799.99 y MXN $1,499.99 se quedan en menudeo.

**Quité un producto y volvió a menudeo.**  
El mes anterior no calificaba y el pedido ya no llega a MXN $1,500 a precio de menudeo.

**¿La excepción deja al cliente como mayorista?**  
No. Solo este ticket. El tipo de cliente no cambia.

**No deja cambiar la lista a mano.**  
Es el comportamiento esperado. La caja elige la lista.

**Sin internet.**  
Menudeo, con aviso de que no se pudo consultar el historial. Solo un gerente puede autorizar otra lista, con NIP y motivo.

**El panel no aparece.**  
El control está apagado en esa sucursal, o el navegador sigue con la versión anterior de la caja. Recargue forzando la caché.
