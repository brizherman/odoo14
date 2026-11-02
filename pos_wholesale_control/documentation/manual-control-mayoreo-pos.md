# Guía de uso — Control de precios mayoristas en POS

**Fecha:** 2026-11-01  
**Módulo:** `pos_wholesale_control` 14.0.1.3.1

La caja elige la lista. El cajero no la cambia. El módulo no cambia el tipo de cliente ni los pedidos ya cobrados.

## Reglas

El historial suma todas las sucursales, en hora de Tijuana. Cuentan los pedidos de punto de venta pagados o facturados y las ventas confirmadas. No cuentan borradores, cancelados ni pedidos sin pagar. Una devolución resta el mes de la venta original.

| Tipo | Cuándo califica | Lista |
|---|---|---|
| Mayorista, Público General, Mayorista dormido | Mes anterior de MXN $800, o MTD más este pedido a menudeo de MXN $1,500 | Lista de precios de Mayorista |
| Distribuidores | Mes anterior de MXN $10,000, o MTD más este pedido de MXN $10,000 | Super Precios a Distribuidores |
| Sin cliente, o no alcanza | — | Lista de precios a Público en General |

MXN $800.00, MXN $1,500.00 y MXN $10,000.00 exactos sí califican. Un centavo abajo, no.

MTD contiene solo ventas ya cobradas; el ticket abierto se suma aparte a precio de menudeo. Los clientes Distribuidores permanecen en menudeo hasta alcanzar MXN $10,000 y nunca usan la lista de Mayorista. El total cobrado puede quedar debajo del mínimo después de aplicar la lista que corresponde. Si falta Super Precios cuando corresponde precio de Distribuidor, el pedido queda en menudeo. Si las sucursales del historial no comparten la moneda de la caja, no se suma el historial y queda en menudeo.

## Configuración

Por sucursal, en **Punto de venta → Configuración → Ajustes**, bloque **Control de clientes mayoristas**. Lo hace un **Administrador de mayoreo en POS**. Al instalar o actualizar, **Activar control de mayoreo** queda apagado.

Antes de encenderlo: listas de Público y de Mayorista en MXN y en cada caja; una fila activa por tipo, como en la tabla de arriba; mínimos **800**, **1,500** y **10,000**; zona **America/Tijuana**. Cada caja usa empleados de punto de venta. Quien autorice necesita **Punto de venta / Responsable** y un NIP. Si hay una advertencia amarilla, corríjala. Luego encienda el interruptor, guarde y recargue la caja forzando la caché.

## En la caja

El panel **Control de mayoreo** está arriba de las categorías. El cliente se elige con **Elegir cliente**. Sin cliente, el precio queda en menudeo y no se muestran los meses. El botón de lista dice **Lista de precios bloqueada**.

Al cobrar, el servidor vuelve a calcular. Si la lista no coincide, aparece *No se puede cobrar con la lista seleccionada* y regresa a los productos.

**Excepción de gerente:** vale un solo ticket. Pide NIP y motivo. No cambia el tipo de cliente ni el siguiente ticket. En mayoreo normal, cambiar el cliente borra la excepción. En Distribuidores, el botón solo aparece si no califica, o si no hay historial, y Super Precios está en la caja. Después de autorizar, la decisión automática sigue en menudeo y la etiqueta dice **Distribuidor — excepción de gerente**. El cliente queda bloqueado: hay que abrir un ticket nuevo. Ese ticket no hereda la excepción. Sin historial, el ticket se queda en menudeo y la única salida es esta excepción.

## Después del cobro

Pedido cobrado, pestaña **Mayoreo**. Menú **Punto de venta → Excepciones de mayoreo**: no se crea, no se edita y no se borra. La ven los gerentes de mayoreo.
