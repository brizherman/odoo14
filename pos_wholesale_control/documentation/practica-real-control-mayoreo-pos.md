# Práctica real paso a paso — Control de mayoreo en POS

**Fecha:** 2026-11-01  
**Módulo:** `pos_wholesale_control` 14.0.1.3.1  
**Estado:** Guion para hacer la práctica en la caja  
**Alcance:** Los casos de `capacitacion-control-mayoreo-pos.md` que se pueden ver con estos clientes reales, incluidas las reglas de Distribuidores.

Haga un paso y revise **Debe ver** antes de pasar al siguiente. No cobre ningún ticket. No use **Excepción de gerente**. No cambie la lista a mano: el botón dice **Lista de precios bloqueada**.

## Datos de esta práctica

Los totales de los seis primeros clientes se leyeron la mañana del 2026-11-01. Los cuatro distribuidores que sí califican se leyeron la noche del mismo día. Salen de pedidos de Punto de Venta pagados, terminados o facturados de todas las sucursales. Esos diez clientes no tienen devoluciones de noviembre ni pedidos de venta confirmados en octubre.

La zona horaria es `America/Tijuana`. Octubre es el mes anterior. Para Mayorista el mínimo de ese mes es MXN $800.00. Para Distribuidores el mínimo de ese mes es MXN $10,000.00. Noviembre es el mes actual, marcado **MTD** en el panel. El ticket abierto no entra en noviembre, pero se suma a MTD a precio de menudeo para decidir. Los clientes Distribuidores solo usan el mínimo de MXN $10,000.00; no usan los mínimos de MXN $800.00 ni MXN $1,500.00. Si un cobro de hoy cambia noviembre antes de empezar, use las cifras del panel.

Busque cada cliente por teléfono para no abrir un duplicado.

| Práctica | Cliente | Tipo | Teléfono | Octubre | Noviembre |
|---|---|---|---|---|---|
| Pasos 4 a 8 | JANETT ALEJANDRA MEZA COTA | Mayorista | 6461482456 | MXN $0.00 | MXN $1,229.47 |
| Paso 10 | LUZ AMERICA CASTILLO ESCOBEDO PAPELERIA | Mayorista | 6462690030 | MXN $799.63 | MXN $0.00 |
| Paso 11 | REYNA ACAHUA ARELLANO | Mayorista | 6643667196 | MXN $800.22 | MXN $0.00 |
| Paso 12 | BELDEN DE SONORA | Mayorista | 6646861924 | MXN $3,158.80 | MXN $0.00 |
| Pasos 13 y 14 | ALMA LETICIA MARTINEZ VERDIN | Distribuidores | 6641235327 | MXN $2,447.99 | MXN $0.00 |
| Pasos 15 y 16 | SARA ALICIA CAMACHO | Distribuidores | 6644076716 | MXN $102.02 | MXN $0.00 |
| Pasos 17 y 18 | ZULEMA GUTIERREZ | Distribuidores | 6641289088 | MXN $13,484.97 | MXN $0.00 |
| Mismo caso | ERICKA NOHEMI GUTIERREZ VERDUGO | Distribuidores | 6644923187 | MXN $13,072.13 | MXN $0.00 |
| Mismo caso | ELSA MARISELA ALVARADO NUÑEZ | Distribuidores | 6646818971 | MXN $11,871.54 | MXN $0.00 |
| Mismo caso | PERLA CAROLINA NIÑO VEGA | Distribuidores | 6655213364 | MXN $10,480.99 | MXN $0.00 |

Producto: **Caja Blanca Pastel Dubrin C/25**, referencia interna `CB7P`. Precio de catálogo a público: **MXN $398.24**.

- **2 cajas** quedan debajo de MXN $1,500.00 a menudeo (MXN $796.48).
- **4 cajas** cruzan MXN $1,500.00 a menudeo (MXN $1,592.96).

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

## Paso 4. Elegir a Janett y leer el historial

1. Pulse **Elegir cliente** en la barra de control de mayoreo.
2. Busque `6461482456`.
3. Elija **JANETT ALEJANDRA MEZA COTA**.
4. Cierre la lista de clientes y lea el panel antes de agregar productos.

**Debe ver:**

- Cliente: **JANETT ALEJANDRA MEZA COTA — Mayorista**.
- **Precio:** Menudeo.
- **Lista de precios:** Lista de precios a Publico en General (MXN).
- **Motivo:** Ni el mes anterior ni el acumulado del mes actual más este pedido alcanzan el mínimo de mayoreo.
- Octubre: **MXN $0.00**.
- Noviembre **(MTD):** **MXN $1,229.47**.

Si el nombre no es ese, vuelva a buscar por el teléfono. Si octubre o noviembre no coinciden, anote las cifras del panel y úselas en los pasos siguientes. Octubre tiene que seguir debajo de MXN $800.00 y noviembre debajo de MXN $1,500.00 para que el ticket decida. Noviembre ya trae MXN $1,229.47; faltan MXN $270.53 para activar mayoreo.

## Paso 5. Reactivación — MTD más una caja califican

1. Deje a Janett seleccionada.
2. Busque el producto `CB7P`.
3. Agregue **1** caja.
4. Lea el panel.

**Debe ver:** el panel cambia a **Control de mayoreo — mayoreo**. **Precio** cambia a **Mayoreo** y la lista a Mayorista. El motivo dice que el acumulado del mes actual más este pedido alcanza el mínimo. Noviembre sigue en **MXN $1,229.47** y una caja vale MXN $398.24 a menudeo; juntos suman MXN $1,627.71.

No cobre.

## Paso 6. Cuatro cajas conservan el mayoreo

1. Siga con Janett y la misma caja.
2. Suba la cantidad a **4**.
3. Espere a que desaparezca **Consultando el historial de compras…**.
4. Lea el panel y el total del pedido.

**Debe ver:**

- Título: **Control de mayoreo — mayoreo**.
- **Precio:** Mayoreo.
- **Lista de precios:** Lista de precios de Mayorista (MXN).
- **Motivo:** El acumulado del mes actual más este pedido, a precio de menudeo, alcanza el mínimo de mayoreo.
- Octubre sigue en **MXN $0.00**, debajo de MXN $800.00.
- Noviembre sigue en **MXN $1,229.47**, debajo de MXN $1,500.00.

La caja cambió la lista sola. No toque el botón de lista de precios. Cuatro cajas a menudeo son MXN $1,592.96.

## Paso 7. Al vaciar el pedido vuelve a menudeo

1. Siga con Janett y las 4 cajas. El panel debe estar en mayoreo.
2. Baje la cantidad a **0**.
3. Lea el panel.

**Debe ver:** otra vez **Control de mayoreo — menudeo**, **Precio** en **Menudeo** y la lista de público. Sin ticket abierto, noviembre queda debajo de MXN $1,500.00.

## Paso 8. Caso 6 — el total a pagar puede quedar debajo de $1,500

1. Siga con Janett.
2. Agregue otra vez **1** caja.
3. Confirme que el panel volvió a mayoreo.
4. Compare el **total a pagar** del pedido con MXN $1,500.00.

**Debe ver:**

- El panel permanece en **Mayoreo**.
- La lista sigue siendo **Lista de precios de Mayorista (MXN)**.
- El motivo sigue siendo el acumulado de MTD más el pedido a precio de menudeo.
- El total a pagar puede quedar **debajo** de MXN $1,500.00, porque ya usa precios de mayoreo. Eso no regresa el ticket a menudeo.

No cobre. El panel no muestra el cálculo a menudeo del ticket abierto. La señal es que **Precio** sigue en **Mayoreo** aunque el total cobrado baje de MXN $1,500.00.

## Paso 9. Vaciar el pedido de Janett

1. Ponga la cantidad de `CB7P` en **0** o borre la línea.
2. No pulse **Pago**.

**Debe ver:** pedido vacío. Janett puede seguir seleccionada. El panel vuelve a menudeo porque MTD sin el pedido abierto no llega a MXN $1,500.00. Noviembre sigue en **MXN $1,229.47**.

## Paso 10. Luz América — justo debajo de $800

1. Vacíe el pedido si todavía tiene productos.
2. Pulse **Elegir cliente** en la barra de control de mayoreo y busque `6462690030`.
3. Elija **LUZ AMERICA CASTILLO ESCOBEDO PAPELERIA**.
4. Lea el panel antes de capturar productos.
5. Agregue **2** cajas de `CB7P`.
6. Lea el panel otra vez.

**Debe ver antes de capturar:** tipo **Mayorista**, octubre **MXN $799.63** y noviembre **(MTD) MXN $0.00**.

**Debe ver con 2 cajas:** **Precio** en **Menudeo** y lista de público. El motivo dice que no se alcanza ningún mínimo. MXN $799.63 no llega al mínimo de MXN $800.00, y dos cajas no llegan a MXN $1,500.00 a menudeo.

No cobre. Vacíe el pedido.

## Paso 11. Caso 2 — Reyna, justo arriba de $800

1. Pedido vacío.
2. Busque `6643667196`.
3. Elija **REYNA ACAHUA ARELLANO**. El nombre del registro termina con un espacio; el teléfono identifica el contacto.
4. Lea octubre en el panel.
5. Agregue **2** cajas de `CB7P`.
6. Lea el panel.

**Debe ver:**

- Tipo: **Mayorista**.
- Octubre: **MXN $800.22**.
- Noviembre **(MTD):** **MXN $0.00**.
- **Precio:** Mayoreo, aunque el pedido sea chico.
- **Lista de precios:** Lista de precios de Mayorista (MXN).
- **Motivo:** El mes anterior alcanza el mínimo de mayoreo.

No cobre. Vacíe el pedido.

## Paso 12. Caso 2 otra vez — Belden, historial claro

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

Octubre, que ahora es el mes anterior, pasa de MXN $800.00. El motivo debe ser ese mes. Dos cajas bastan. Noviembre en cero no cambia la decisión.

No cobre. Vacíe el pedido.

## Paso 13. Alma no llega al mínimo de Distribuidor

1. Pedido vacío.
2. Busque `6641235327`.
3. Elija **ALMA LETICIA MARTINEZ VERDIN**. Ese teléfono también está en otros contactos; no elija esos.
4. Lea el panel antes de capturar.
5. Agregue **2** cajas de `CB7P`.
6. Lea el panel otra vez.

**Debe ver antes y después de las 2 cajas:**

- Tipo: **Distribuidores**.
- Octubre: **MXN $2,447.99**.
- Noviembre **(MTD):** **MXN $0.00**.
- **Mes anterior:** **MXN $2,447.99**.
- **Mínimo de distribuidor:** **MXN $10,000.00**.
- **Precio:** Menudeo / Público general.
- **Lista de precios:** Lista de precios a Publico en General (MXN).
- **Motivo:** No alcanza el mínimo de distribuidor. El pedido queda en menudeo.

Aunque octubre supera MXN $800.00, el tipo Distribuidores no usa ese mínimo ni la lista de Mayorista.

Puede aparecer **Excepción de gerente**. No la pulse.

No cobre. Deje las 2 cajas para el paso siguiente.

## Paso 14. Alma con cuatro cajas sigue en menudeo

1. Siga con Alma y las 2 cajas.
2. Suba la cantidad a **4**.
3. Lea el panel.

**Debe ver:**

- **Precio:** Menudeo / Público general.
- **Lista de precios:** Lista de precios a Publico en General (MXN).
- **Motivo:** No alcanza el mínimo de distribuidor. El pedido queda en menudeo.
- Octubre sigue en **MXN $2,447.99** y noviembre en **MXN $0.00**.
- **Mínimo de distribuidor:** **MXN $10,000.00**.

Aunque cuatro cajas superan MXN $1,500.00, un cliente Distribuidores permanece en menudeo hasta alcanzar MXN $10,000.00.

No cobre. Vacíe el pedido.

## Paso 15. Sara con dos cajas sigue en menudeo

1. Pedido vacío.
2. Busque `6644076716`.
3. Elija **SARA ALICIA CAMACHO**.
4. Lea el panel antes de capturar.
5. Agregue **2** cajas de `CB7P`.
6. Lea el panel.

**Debe ver:**

- Tipo: **Distribuidores**.
- Octubre: **MXN $102.02**.
- Noviembre **(MTD):** **MXN $0.00**.
- **Mes anterior:** **MXN $102.02**.
- **Mínimo de distribuidor:** **MXN $10,000.00**.
- Con 2 cajas, **Precio** en **Menudeo / Público general** y lista de público.
- **Motivo:** El mes anterior no alcanza el mínimo de distribuidor.

El tipo Distribuidores no da Super Precios por sí solo. MTD más el pedido tampoco alcanza MXN $10,000.00. No pulse **Excepción de gerente**.

## Paso 16. Sara con cuatro cajas sigue en menudeo

1. Siga con Sara y las 2 cajas.
2. Suba la cantidad a **4**.
3. Lea el panel.

**Debe ver:**

- **Precio:** Menudeo / Público general.
- **Lista de precios:** Lista de precios a Publico en General (MXN).
- **Motivo:** No alcanza el mínimo de distribuidor. El pedido queda en menudeo.
- Octubre sigue en **MXN $102.02** y noviembre en **MXN $0.00**.

Cuatro cajas superan MXN $1,500.00, pero ese mínimo no aplica a Distribuidores. El caso que recibe Super Precios es el paso 17.

No cobre. Vacíe el pedido.

## Paso 17. Zulema ya trae Super Precios

1. Pedido vacío.
2. Busque `6641289088`.
3. Elija **ZULEMA GUTIERREZ**.
4. Lea el panel antes de capturar productos.

**Debe ver:**

- Tipo: **Distribuidores**.
- Octubre: **MXN $13,484.97**.
- Noviembre **(MTD):** **MXN $0.00**.
- **Mes anterior:** **MXN $13,484.97**.
- **Mínimo de distribuidor:** **MXN $10,000.00**.
- **Precio:** Distribuidor.
- **Lista de precios:** Super Precios a Distribuidores (MXN).
- **Motivo:** El mes anterior alcanza el mínimo de distribuidor.

No es la lista de Mayorista. El botón **Excepción de gerente** no debe aparecer, porque ya califica. También calificaría si MTD más el ticket abierto llegaran a MXN $10,000.00.

Si Zulema no coincide, use el mismo paso con Ericka (`6644923187`), Elsa (`6646818971`) o Perla (`6655213364`). Las tres también pasan de MXN $10,000.00 en octubre. Lea el octubre del panel, no el de esta tabla, si un cobro de hoy lo cambió.

## Paso 18. Dos cajas no le quitan Super Precios

1. Siga con Zulema, o con la distribuidora que haya elegido en el paso 17.
2. Agregue **2** cajas de `CB7P`.
3. Lea el panel.

**Debe ver:**

- **Precio:** Distribuidor.
- **Lista de precios:** Super Precios a Distribuidores (MXN).
- **Motivo:** El mes anterior alcanza el mínimo de distribuidor.
- Octubre no cambió. Noviembre sigue en **MXN $0.00**.

Dos cajas a menudeo son MXN $796.48. Como ya calificó por el mes anterior, la lista se queda en Super Precios.

No cobre. Vacíe el pedido.

## Paso 19. Cerrar la práctica sin cobrar

1. Ponga la cantidad en **0** o borre la línea.
2. Confirme que el pedido quedó vacío.
3. No pulse **Pago**.
4. No cierre la sesión si su turno sigue abierto.

**Debe ver:** pedido en cero. Ningún pedido nuevo cobrado por esta práctica.

Si en algún paso el panel no coincide con **Debe ver**, deténgase. Anote el paso, el cliente, **Precio**, **Lista de precios**, **Motivo** y los montos de octubre y noviembre. No fuerce la lista ni cobre para “corregirlo”.
