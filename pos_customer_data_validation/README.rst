Revisión de datos del cliente en POS
====================================

Estado de esta entrega
----------------------

Módulo para Odoo 14 Community. Backend, popup e integración del pago implementados
y verificados en bases aisladas, incluida la combinación con mayoreo y vendedor.
Entrega completada: implementación, validación, documentación, traducciones y
revisión final de alcance del plan cerradas. El registro conserva los límites
de las pruebas; el HttpCase nativo sigue omitido según se explica más abajo.

Estado y evidencia, desde la raíz del proyecto:
`plan de tareas <../../../tasks/tasks-pos-customer-data-validation.md>`_ y
`verificación consolidada <../../../VERIFICATION.md>`_. La instalación en
``produccion_dev`` se realizó después del cierre del plan con autorización
explícita; el módulo está instalado en versión 14.0.1.0.0. Producción no se
modificó. La comprobación manual del POS de la réplica queda para su uso posterior.

Depende de ``alta_mayoristas`` y ``point_of_sale``. No modifica sus archivos ni
instala mayoreo, vendedor o módulos Enterprise.

Uso en caja
-----------

Con el módulo instalado y la sesión POS abierta:

1. Prepara el ticket, selecciona el cliente y entra a la pantalla de pago.
2. Al pulsar **Validar**, se abre **Revisar datos del cliente**, también cuando
   los cuatro datos están completos. Funciona en escritorio y móvil.
3. Revisa con el cliente **Nombre**, **WhatsApp**, **Tipo de Cliente** y
   **Tarifa**, junto con la fecha de última modificación de cada dato.
4. Corrige lo necesario y pulsa **Guardar**, o confirma sin editar si todo
   sigue correcto. El módulo guarda o confirma con el servidor, actualiza
   el cliente en el POS y continúa ese mismo intento de pago una sola vez.
5. Atiende los controles habituales: vendedor, reglas comerciales y pago.
   Si bloquean el cobro, corrige la causa; el siguiente clic manual en
   **Validar** vuelve a abrir la revisión del cliente.

Un ticket sin cliente sigue las validaciones habituales sin abrir esta revisión.
El módulo no obliga a seleccionar cliente en todas las ventas.

Datos obligatorios y tarifa
---------------------------

- **Nombre**: debe contener texto; los espacios por sí solos no son válidos.
- **WhatsApp**: corresponde al campo móvil del contacto (``mobile``); debe
  contener texto. Tener teléfono fijo no sustituye este dato. El módulo no
  comprueba que el número tenga una cuenta WhatsApp ni envía mensajes.
- **Tipo de Cliente**: admite Mayorista, Distribuidores, Público en general
  y Mayorista dormido, reutilizando las opciones de ``alta_mayoristas``.
- **Tarifa**: debe estar disponible para esa caja y corresponder al tipo de
  cliente según las reglas existentes de ``alta_mayoristas``. Al cambiar el tipo,
  se conserva una tarifa compatible o se propone la primera correspondiente;
  revisa la selección antes de guardar.

Los faltantes se señalan juntos y el formulario conserva las ediciones para
corregirlos. La revisión lee los valores actuales del servidor, por lo que
incluye cambios hechos desde la ficha del contacto antes de abrir el popup.

La tarifa mostrada es la efectiva de la ficha del cliente en la compañía del
POS, incluida la predeterminada que resuelve Odoo. La tarifa del ticket no
sustituye una tarifa ausente en la ficha. Confirmar sin cambios no obliga a
igualar ambas; los controles comerciales existentes siguen decidiendo el precio
del ticket. Un cambio de tipo o tarifa puede recalcularlo. Se conservan sus
productos y pagos: si el nuevo total supera lo pagado, el cobro queda pendiente.

Guardar, cancelar y errores
---------------------------

**Guardar** requiere conexión con el servidor incluso al confirmar sin cambios.
No guarda la revisión para enviarla después sin conexión. Si todos los datos
son válidos, no hace falta pulsar **Validar** otra vez para continuar.

**Cancelar**, antes de enviar el guardado, cierra el popup y descarta sus
ediciones sin guardar el contacto ni finalizar la venta. Conserva los productos
y las líneas de pago del ticket. Mientras se está guardando, **Guardar**,
**Cancelar** y Escape quedan bloqueados: espera la respuesta del servidor.
No se promete revertir una escritura que ya fue enviada.

Ante un error de guardado o conexión, el popup conserva lo escrito y no continúa
el cobro. Revisa el mensaje y reintenta cuando se resuelva la causa, o cancela
cuando el guardado deje de estar pendiente. Un corte de conexión puede ocurrir
después de que el servidor haya recibido la escritura; al volver a abrir la
revisión se leen los datos actuales.

Si cambia el ticket o el cliente durante la operación, la respuesta anterior no
puede finalizar otro ticket: cancela esa revisión y vuelve a validar el actual.
Una revisión no queda autorizada para ventas posteriores. La confirmación
interna de un importe grande continúa el mismo intento sin repetir el popup.

Guardar el contacto y finalizar la venta son operaciones distintas. Si después
del guardado faltan vendedor, pago o condiciones comerciales, el contacto puede
haber quedado actualizado aunque el ticket siga abierto. Cancelar un intento
posterior no deshace esa actualización ya confirmada.

Acceso y configuración
----------------------

El usuario necesita acceso a Punto de Venta, a la configuración y compañía de
la caja, lectura de las tarifas y permisos actuales de lectura y edición del
contacto. Incluso confirmar sin cambios comprueba el permiso de edición.
El módulo respeta las reglas de acceso; no concede permisos para salvar un
rechazo. Un administrador debe resolver las restricciones o tarifas disponibles
mediante la configuración habitual de Odoo.

No se añaden requisitos globales que obliguen a completar estos cuatro datos
al crear cualquier contacto fuera de esta revisión POS. Si están instalados
``pos_wholesale_control`` u ``odf_pos_salesperson``, sus controles siguen activos.

Traducciones
------------

Los mensajes propios están preparados para traducción y se incluye ``i18n/es.po``.
Odoo 14 carga este catálogo base también para español de México (``es_MX``).
Se comprobó la carga del catálogo, los cuatro errores de campos faltantes y el
tour de 14 pasos con un usuario ``es_MX``. Los mensajes heredados de Odoo y de
los módulos comerciales usan sus respectivos catálogos; este addon no modifica
sus archivos ni sustituye sus mensajes.

Contrato del servidor
---------------------

``res.partner.pos_customer_data_read(partner_id, config_id)`` devuelve los datos
efectivos del contacto, sus fechas, los tipos existentes y las tarifas de la
configuración. Incluye las correspondencias tipo/tarifa calculadas con las
reglas de ``alta_mayoristas``.

``res.partner.pos_customer_data_save(partner_id, config_id, changes)`` acepta
únicamente ``name``, ``mobile`` (WhatsApp), ``customer_type`` y
``property_product_pricelist``. La interfaz envía solo los campos
editados, para conservar modificaciones concurrentes de los demás campos.
Un diccionario vacío confirma con el servidor sin renovar fechas.

Se comprueban nombre y WhatsApp no vacíos, los cuatro tipos admitidos y la tarifa
efectiva, disponible y correspondiente al tipo. El teléfono fijo no sustituye
a WhatsApp. La compañía procede de la configuración accesible del POS.
El contrato no recibe ni utiliza la tarifa del ticket.

Requiere conexión, acceso al POS, lectura de configuración/tarifas y permisos
actuales de edición del contacto. No eleva los permisos de estas operaciones.
Un bloqueo de fila serializa los guardados; un savepoint revierte también cambios
parciales si falla una regla heredada. Las ediciones efectivas pasan por
``create_from_ui``. No se crean ni finalizan pedidos desde esta API.

Fechas y límites
----------------

Nombre, WhatsApp y tipo tienen fechas independientes calculadas ante cambios
reales por ORM, incluida la creación múltiple. Los registros históricos no se
rellenan al instalar. Fechas vacías significan **Sin fecha registrada**.
La antigüedad es informativa y no impide confirmar datos completos.
Las fechas se muestran en la zona horaria del usuario de Odoo. Guardar sin
cambios no renueva las fechas; cambiar solo WhatsApp no renueva las de Nombre
o Tipo de Cliente. No se puede editar una fecha desde el popup. La leyenda
**Sin fecha registrada** no significa que falte el dato ni bloquea el cobro.

La evidencia de tarifa se guarda por contacto y compañía, con el ID efectivo y
una huella de sus fuentes de resolución. Contadores internos detectan incluso
cambios de ida y vuelta dentro del mismo segundo. No se usa ``write_date`` como
fecha del dato. Las fechas y contadores rechazan alteraciones mediante RPC.

Un cambio de país, contacto comercial, propiedad predeterminada, tarifa o grupos
de países puede invalidar evidencia. Si no se puede demostrar continuidad del
valor, se devuelve fecha desconocida; no se atribuye una fecha antigua a otro
valor o compañía. La invalidación es conservadora: cambios de configuración
de precios pueden hacer desconocidas fechas de otros contactos de la compañía.
Las fuentes compartidas pueden invalidar evidencia en todas las compañías.
Crear o editar una propiedad específica de otro cliente no invalida por sí solo
todas las fechas.

La lectura técnica elevada de propiedades solo calcula una huella; no devuelve
sus registros al cajero. Las revisiones internas se incrementan mediante SQL
parametrizado después de operaciones ORM autorizadas, exclusivamente sobre
metadatos del addon. Las modificaciones de negocio realizadas directamente por
SQL quedan fuera de la garantía de seguimiento.

Pruebas
-------

Desde la raíz, eligiendo una base de prueba permitida y libre para una nueva
instalación, sin utilizar ``produccion_dev``::

    make test-module name=pos_customer_data_validation db=odoo_test_customer_readme_01

El nombre anterior es un ejemplo; comprueba su disponibilidad antes de ejecutar.
El comando usa ``--no-http`` y comprueba backend, no recorridos de navegador.
Resultados ya registrados en la verificación consolidada:

- 28 pruebas backend sin fallos ni errores, también con módulos comerciales.
- 11 grupos de regresión básica y 14 con mayoreo/vendedor en navegador.
- Tour registrado de Odoo: 14 pasos aprobados con Chromium del host, un pedido
  pagado y fechas históricas conservadas.
- Runners Node de popup y pago correctos; usan objetos de prueba y complementan
  la evidencia de navegador.

El ``HttpCase`` nativo fue seleccionado y omitido: faltan ``websocket-client``
y Chrome/Chromium en el runtime conservado. El tour se ejecutó con navegador
del host contra HTTP interno, sin instalar paquetes ni publicar puertos extra.
No se presenta el resultado alternativo como aprobación del harness Python.

Los errores de permisos/red de interfaz y el cambio de decisión comercial se
inyectaron en transporte para comprobar sus rechazos. Los permisos reales del
servidor están cubiertos por pruebas ORM. La evidencia no acredita un rechazo
comercial autónomo del backend ni una prueba de carga concurrente entre procesos.
Los logs, bases, capturas sintéticas y comandos exactos están en los enlaces
de verificación y tareas indicados al inicio.
