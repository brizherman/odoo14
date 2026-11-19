Productos solicitados en el POS
===============================

Para Odoo 14 Community. Instala el módulo técnico ``pos_product_requests``
y recarga la interfaz del punto de venta.

Registrar un faltante
---------------------

En la pantalla de venta, pulsa **Registrar faltante**. En móviles, abre
primero el panel del ticket con **Revisar**. Escribe un producto
con la descripción que dio el cliente y elige **Sin stock**,
**No lo manejamos** o **No existe**. Pulsa **Guardar** para volver al ticket
cuando el servidor confirme. Puedes registrar con el ticket vacío o durante
una venta. Usa **Cancelar** para descartar el formulario.

Si falla el guardado, el formulario conserva el texto y el motivo. Pulsa
**Guardar** de nuevo con los mismos datos. El servidor reconoce el reintento
de la misma captura aunque se haya perdido la primera confirmación.

Consultar faltantes
-------------------

Pulsa el icono **Faltantes** en la barra superior. Cuando está activa la opción
**Gestionar pedidos**, el icono aparece junto a la lupa. La lista muestra el
producto solicitado, el motivo y la fecha y hora, con los más recientes primero.
Pulsa **Volver** para retomar el ticket.

El historial se comparte entre cajas y turnos que usan la misma configuración
de POS. Se requiere una sesión abierta y conexión al servidor para guardar y
consultar.

Consultar faltantes desde el backend
------------------------------------

Con el permiso de administrador de Punto de venta, abre **Punto de venta →
Órdenes → Faltantes**. Busca por producto, punto de venta o motivo y abre
cualquier fila para ver el registro completo. La lista y el detalle son de
solo lectura y muestran los registros de las compañías permitidas.
