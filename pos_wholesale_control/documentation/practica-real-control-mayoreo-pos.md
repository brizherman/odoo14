# Práctica real paso a paso — Control de mayoreo en POS

**Fecha:** 2026-11-02  
**Módulo:** `pos_wholesale_control` 14.0.1.3.1  
**Estado:** Guion para hacer la práctica en la caja  
**Alcance:** Casos reales leídos la mañana del 2026-11-02, después de las ventas que movieron los totales del 2026-11-01.

Haga un paso y revise **Debe ver** antes de pasar al siguiente. No cobre ningún ticket. No use **Excepción de gerente**. No cambie la lista a mano: el botón dice **Lista de precios bloqueada**.

## Datos de esta práctica

Los totales salen de la misma cuenta que usa la caja: todas las sucursales, en hora de Tijuana. Cuentan los pedidos de punto de venta pagados, terminados o facturados y las ventas confirmadas. Una devolución resta el mes de la venta original.

La zona horaria es `America/Tijuana`. Octubre es el mes anterior. Noviembre es el mes actual, marcado **MTD** en el panel. El ticket abierto no entra en noviembre, pero se suma a MTD para decidir.

| Tipo | Regla | Lista |
|---|---|---|
| Mayorista | Octubre de MXN $800.00, o noviembre más este pedido a menudeo de MXN $1,500.00 | Lista de precios de Mayorista |
| Distribuidores | Octubre de MXN $10,000.00, o noviembre más este pedido a menudeo de MXN $10,000.00 | Super Precios a Distribuidores |
| Distribuidores debajo de MXN $10,000.00 | Se queda en menudeo. No usa MXN $800.00 ni MXN $1,500.00 | Lista de precios a Público en General |

Busque cada cliente por teléfono para no abrir un duplicado.

| Práctica | Cliente | Tipo | Teléfono | Octubre | Noviembre |
|---|---|---|---|---|---|
| Paso 4 | JANETT ALEJANDRA MEZA COTA | Mayorista | 6461482456 | MXN $0.00 | MXN $1,560.64 |
| Pasos 5 a 8 | LUZ AMERICA CASTILLO ESCOBEDO PAPELERIA | Mayorista | 6462690030 | MXN $799.63 | MXN $1,290.30 |
| Pasos 9 y 10 | KENIA RODRIGUEZ | Mayorista | 6647313257 | MXN $799.44 | MXN $0.00 |
| Paso 11 | REYNA ACAHUA ARELLANO | Mayorista | 6643667196 | MXN $800.22 | MXN $0.00 |
| Paso 12 | BELDEN DE SONORA | Mayorista | 6646861924 | MXN $3,158.80 | MXN $0.00 |
| Pasos 13 y 14 | MARIA ISABEL TEOSOL AGUATZI | Distribuidores | 6643865490 | MXN $8,631.90 | MXN $0.00 |
| Paso 15 | LOURDES JASSO GALVAN | Distribuidores | 6621484929 | MXN $514.42 | MXN $0.00 |
| Pasos 16 y 17 | ZULEMA GUTIERREZ | Distribuidores | 6641289088 | MXN $13,484.97 | MXN $0.00 |
| Mismo caso | ERICKA NOHEMI GUTIERREZ VERDUGO | Distribuidores | 6644923187 | MXN $13,072.13 | MXN $0.00 |
| Mismo caso | ELSA MARISELA ALVARADO NUÑEZ | Distribuidores | 6646818971 | MXN $11,871.54 | MXN $0.00 |
| Mismo caso | PERLA CAROLINA NIÑO VEGA | Distribuidores | 6655213364 | MXN $10,480.99 | MXN $0.00 |

Producto: **Caja Blanca Pastel Dubrin C/25**, referencia interna `CB7P`.

- Precio de catálogo a público: **MXN $398.24**.
- Referencia que usa la caja, con IVA de 8%: **MXN $430.10** por caja.
- **2 cajas** a menudeo: **MXN $860.20**. Quedan debajo de MXN $1,500.00.
- **4 cajas** a menudeo: **MXN $1,720.40**. Cruzan MXN $1,500.00.
- **23 cajas** a menudeo: **MXN $9,892.28**. Quedan debajo de MXN $10,000.00.
- **24 cajas** a menudeo: **MXN $10,322.38**. Cruzan MXN $10,000.00.

El total que aparece a la izquierda puede ser menor, porque ya usa la lista concedida. La decisión no se lee en ese total.

En el panel lea el título, el cliente, **Precio**, **Lista de precios**, **Motivo** y los meses. El mes más antiguo se puede ignorar. Octubre y noviembre (**MTD**) son los que importan. En pantalla los meses salen como **octubre 2026** y **noviembre 2026 (MTD)**.

El control está encendido solo en **Factor Fiesta | Tijuana Insurgentes**.

---

## Paso 1. Abrir la caja

1. Entre a **Punto de venta**.
2. Abra una sesión en **Factor Fiesta | Tijuana Insurgentes**, donde **Activar control de mayoreo** ya está encendido.
3. Si acaba de actualizar el módulo, recargue la caja con una actualización forzada del navegador.

**Debe ver:** la pantalla de productos de la caja, con un pedido vacío.

## Paso 2. Confirmar que el control está activo

1. Mire la parte superior del panel de productos, encima de las categorías.
2. No seleccione cliente todavía.

**Debe ver:** el panel **Control de mayoreo — menudeo**. El botón del cliente dice **Elegir cliente**. **Precio** dice **Menudeo**. **Motivo** pide seleccionar un cliente. No aparecen los meses.

Si el panel no está, esta sucursal no tiene el control activo. Cambie a Insurgentes antes de seguir.

## Paso 3. Dejar el pedido vacío

1. Si hay productos, selecciónelos y ponga la cantidad en **0**, o bórrelos con el teclado de la caja.
2. No pulse **Pago**.

**Debe ver:** el pedido en cero y sin líneas.

Repita este paso cada vez que el guion diga que el pedido debe quedar vacío.

## Paso 4. Janett — noviembre ya cruzó $1,500

1. Pulse **Elegir cliente** en la barra de control de mayoreo.
2. Busque `6461482456`.
3. Elija **JANETT ALEJANDRA MEZA COTA**.
4. No agregue productos.

**Debe ver:**

- Cliente: **JANETT ALEJANDRA MEZA COTA — Mayorista**.
- **Precio:** Mayoreo.
- **Lista de precios:** Lista de precios de Mayorista (MXN).
- **Motivo:** El mes actual alcanza el mínimo de mayoreo.
- Octubre: **MXN $0.00**.
- Noviembre **(MTD):** **MXN $1,560.64**.

El pedido vacío ya califica porque noviembre, sin este ticket, pasa de MXN $1,500.00. El 2026-11-01 noviembre estaba en MXN $1,229.47; una venta posterior lo subió.

No cobre. Vacíe el pedido si se agregó algo.

## Paso 5. Luz América — el pedido vacío sigue en menudeo

1. Pedido vacío.
2. Busque `6462690030`.
3. Elija **LUZ AMERICA CASTILLO ESCOBEDO PAPELERIA**.
4. Lea el panel antes de capturar productos.

**Debe ver:**

- Tipo: **Mayorista**.
- Octubre: **MXN $799.63**, debajo de MXN $800.00.
- Noviembre **(MTD):** **MXN $1,290.30**, debajo de MXN $1,500.00.
- **Precio:** Menudeo.
- **Lista de precios:** Lista de precios a Publico en General (MXN).
- **Motivo:** Ni el mes anterior ni el acumulado del mes actual más este pedido alcanzan el mínimo de mayoreo.

Faltan MXN $209.70 de referencia a menudeo para activar mayoreo.

## Paso 6. Luz América — una caja activa mayoreo

1. Siga con Luz América.
2. Busque el producto `CB7P`.
3. Agregue **1** caja.
4. Lea el panel.

**Debe ver:**

- Título: **Control de mayoreo — mayoreo**.
- **Precio:** Mayoreo.
- **Lista de precios:** Lista de precios de Mayorista (MXN).
- **Motivo:** El acumulado del mes actual más este pedido, a precio de menudeo, alcanza el mínimo de mayoreo.
- Octubre sigue en **MXN $799.63**.
- Noviembre sigue en **MXN $1,290.30**.

Noviembre más una caja a menudeo suman MXN $1,720.40. La caja cambió la lista sola.

No cobre.

## Paso 7. Al quitar la caja vuelve a menudeo

1. Siga con Luz América y la caja.
2. Ponga la cantidad en **0**.
3. Lea el panel.

**Debe ver:** otra vez **Control de mayoreo — menudeo**, **Precio** en **Menudeo** y la lista de público. Noviembre sigue en **MXN $1,290.30**, debajo de MXN $1,500.00.

## Paso 8. El total a pagar puede quedar debajo de $1,500

1. Siga con Luz América.
2. Agregue otra vez **1** caja de `CB7P`.
3. Confirme que el panel volvió a mayoreo.
4. Compare el total a pagar del pedido con MXN $1,500.00.

**Debe ver:**

- El panel permanece en **Mayoreo**.
- La lista sigue siendo **Lista de precios de Mayorista (MXN)**.
- El total a pagar puede quedar **debajo** de MXN $1,500.00, porque ya usa precios de mayoreo.

La referencia de la decisión sigue siendo MXN $430.10 a menudeo, no el total rebajado.

No cobre. Vacíe el pedido.

## Paso 9. Kenia — justo debajo de $800

1. Pedido vacío.
2. Busque `6647313257`.
3. Elija **KENIA RODRIGUEZ**.
4. Lea el panel antes de capturar.
5. Agregue **2** cajas de `CB7P`.
6. Lea el panel otra vez.

**Debe ver antes de capturar:** tipo **Mayorista**, octubre **MXN $799.44** y noviembre **(MTD) MXN $0.00**.

**Debe ver con 2 cajas:** **Precio** en **Menudeo** y lista de público. El motivo dice que no se alcanza ningún mínimo. MXN $799.44 no llega a MXN $800.00, y dos cajas a menudeo son MXN $860.20.

No cobre. Deje las 2 cajas para el paso siguiente.

## Paso 10. Kenia — cuatro cajas cruzan $1,500

1. Siga con Kenia y las 2 cajas.
2. Suba la cantidad a **4**.
3. Lea el panel.
4. Después baje la cantidad a **0**.

**Debe ver con 4 cajas:**

- **Precio:** Mayoreo.
- **Lista de precios:** Lista de precios de Mayorista (MXN).
- **Motivo:** El acumulado del mes actual más este pedido, a precio de menudeo, alcanza el mínimo de mayoreo.
- Octubre sigue en **MXN $799.44** y noviembre en **MXN $0.00**.

Cuatro cajas a menudeo son MXN $1,720.40. Al volver a cero, el panel regresa a menudeo.

No cobre.

## Paso 11. Reyna — justo arriba de $800

1. Pedido vacío.
2. Busque `6643667196`.
3. Elija **REYNA ACAHUA ARELLANO**. El nombre del registro termina con un espacio; el teléfono identifica el contacto.
4. Agregue **2** cajas de `CB7P`.
5. Lea el panel.

**Debe ver:**

- Tipo: **Mayorista**.
- Octubre: **MXN $800.22**.
- Noviembre **(MTD):** **MXN $0.00**.
- **Precio:** Mayoreo, aunque el pedido sea chico.
- **Lista de precios:** Lista de precios de Mayorista (MXN).
- **Motivo:** El mes anterior alcanza el mínimo de mayoreo.

No cobre. Vacíe el pedido.

## Paso 12. Belden — historial claro

1. Pedido vacío.
2. Busque `6646861924`.
3. Elija **BELDEN DE SONORA**.
4. Agregue **2** cajas de `CB7P`.
5. Lea el panel.

**Debe ver:**

- Tipo: **Mayorista**.
- Octubre: **MXN $3,158.80**.
- Noviembre **(MTD):** **MXN $0.00**.
- **Precio:** Mayoreo.
- **Lista de precios:** Lista de precios de Mayorista (MXN).
- **Motivo:** El mes anterior alcanza el mínimo de mayoreo.

Octubre pasa de MXN $800.00. Dos cajas bastan. Noviembre en cero no cambia la decisión.

No cobre. Vacíe el pedido.

## Paso 13. María Isabel — arriba de $800 y sigue en menudeo

1. Pedido vacío.
2. Busque `6643865490`.
3. Elija **MARIA ISABEL TEOSOL AGUATZI**.
4. Lea el panel antes de capturar.
5. Agregue **4** cajas de `CB7P`.
6. Lea el panel otra vez.

**Debe ver antes y después de las 4 cajas:**

- Tipo: **Distribuidores**.
- Octubre: **MXN $8,631.90**.
- Noviembre **(MTD):** **MXN $0.00**.
- **Mínimo de distribuidor:** **MXN $10,000.00**.
- **Precio:** Menudeo / Público general.
- **Lista de precios:** Lista de precios a Publico en General (MXN).
- **Motivo:** No alcanza el mínimo de distribuidor. El pedido queda en menudeo.

Octubre supera MXN $800.00 y cuatro cajas superan MXN $1,500.00. Esas dos reglas no aplican a un cliente Distribuidores. Octubre tampoco se suma a noviembre para llegar a MXN $10,000.00.

Puede aparecer **Excepción de gerente**. No la pulse.

No cobre. Deje el pedido para el paso siguiente.

## Paso 14. María Isabel — 23 cajas siguen en menudeo y 24 activan Distribuidor

1. Siga con María Isabel.
2. Suba la cantidad a **23**.
3. Lea el panel.
4. Suba la cantidad a **24**.
5. Lea el panel y el total a pagar.
6. Baje la cantidad a **0**.

**Debe ver con 23 cajas:** sigue en menudeo y en la lista de público. Veintitrés cajas a menudeo son MXN $9,892.28, debajo de MXN $10,000.00.

**Debe ver con 24 cajas:**

- **Precio:** Distribuidor.
- **Lista de precios:** Super Precios a Distribuidores (MXN).
- **Motivo:** El acumulado del mes actual más este pedido alcanza el mínimo de distribuidor.
- Octubre sigue en **MXN $8,631.90** y noviembre en **MXN $0.00**.

Veinticuatro cajas a menudeo son MXN $10,322.38. El total a pagar queda cerca de MXN $6,916 porque Super Precios es más bajo. Ese total no decide la regla.

Al volver a cero, el panel regresa a menudeo.

No cobre.

## Paso 15. Lourdes — debajo de $800 también sigue en menudeo

1. Pedido vacío.
2. Busque `6621484929`.
3. Elija **LOURDES JASSO GALVAN**.
4. Agregue **4** cajas de `CB7P`.
5. Lea el panel.

**Debe ver:**

- Tipo: **Distribuidores**.
- Octubre: **MXN $514.42**.
- Noviembre **(MTD):** **MXN $0.00**.
- **Mínimo de distribuidor:** **MXN $10,000.00**.
- **Precio:** Menudeo / Público general.
- **Lista de precios:** Lista de precios a Publico en General (MXN).
- **Motivo:** No alcanza el mínimo de distribuidor. El pedido queda en menudeo.

Aunque cuatro cajas cruzan MXN $1,500.00, Lourdes no recibe la lista de Mayorista.

No cobre. Vacíe el pedido.

## Paso 16. Zulema ya trae Super Precios

1. Pedido vacío.
2. Busque `6641289088`.
3. Elija **ZULEMA GUTIERREZ**.
4. Lea el panel antes de capturar productos.

**Debe ver:**

- Tipo: **Distribuidores**.
- Octubre: **MXN $13,484.97**.
- Noviembre **(MTD):** **MXN $0.00**.
- **Mínimo de distribuidor:** **MXN $10,000.00**.
- **Precio:** Distribuidor.
- **Lista de precios:** Super Precios a Distribuidores (MXN).
- **Motivo:** El mes anterior alcanza el mínimo de distribuidor.

No es la lista de Mayorista. El botón **Excepción de gerente** no debe aparecer, porque ya califica.

Si Zulema no coincide, use el mismo paso con Ericka (`6644923187`), Elsa (`6646818971`) o Perla (`6655213364`). Las tres también pasan de MXN $10,000.00 en octubre y noviembre sigue en cero. Lea el octubre del panel, no el de esta tabla, si un cobro de hoy lo cambió.

## Paso 17. Dos cajas no le quitan Super Precios

1. Siga con Zulema, o con la distribuidora que haya elegido en el paso 16.
2. Agregue **2** cajas de `CB7P`.
3. Lea el panel.

**Debe ver:**

- **Precio:** Distribuidor.
- **Lista de precios:** Super Precios a Distribuidores (MXN).
- **Motivo:** El mes anterior alcanza el mínimo de distribuidor.
- Octubre no cambió. Noviembre sigue en **MXN $0.00**.

Dos cajas a menudeo son MXN $860.20. Como ya calificó por octubre, la lista se queda en Super Precios.

No cobre. Vacíe el pedido.

## Paso 18. Cerrar la práctica sin cobrar

1. Ponga la cantidad en **0** o borre la línea.
2. Confirme que el pedido quedó vacío.
3. No pulse **Pago**.
4. No cierre la sesión si su turno sigue abierto.

**Debe ver:** pedido en cero. Ningún pedido nuevo cobrado por esta práctica.

Si en algún paso el panel no coincide con **Debe ver**, deténgase. Anote el paso, el cliente, **Precio**, **Lista de precios**, **Motivo** y los montos de octubre y noviembre. No fuerce la lista ni cobre para corregirlo.
