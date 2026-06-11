# Contexto Formal Para Codex: FVoltData

Este documento define el contexto de producto, arquitectura, reglas tecnicas y estado actual de FVoltData para orientar nuevas sesiones de trabajo en Codex. Debe leerse antes de iniciar cualquier etapa nueva.

## 1. Identidad Del Producto

**Nombre:** FVoltData

**Descripcion:** FVoltData es una herramienta interactiva y guiada para estimar potencial solar, produccion fotovoltaica, ahorro energetico, respaldo ante apagones y rentabilidad operativa.

**Objetivo general:** evolucionar el prototipo inicial hacia una herramienta interactiva de diseno progresivo. Para empresas de gran escala, la prioridad no es solo estimar ahorro tarifario, sino mitigar danos operativos causados por apagones. El software debe guiar al usuario paso a paso para dimensionar un sistema de respaldo inteligente basado en BESS + Solar, justificado por el costo de la inaccion, sin saturar la interfaz para consultas rapidas.

## 2. Principios Generales Del Producto

- La app debe funcionar como una experiencia progresiva.
- El usuario debe poder obtener una vista rapida sin llenar todos los modulos.
- Los modulos avanzados deben activarse solo cuando el usuario ingresa datos relacionados.
- La interfaz debe ser compacta, profesional y tipo dashboard.
- Evitar textos largos visibles por default.
- Usar expanders para explicaciones tecnicas.
- No usar emojis en ninguna parte de la interfaz.
- No mostrar JSON, tracebacks ni HTML visible al usuario.
- No crear widgets falsos con HTML.
- Usar componentes nativos de Streamlit siempre que sea posible.
- CSS ligero esta permitido para tarjetas, badges, chips, bordes, espaciado y tipografia.
- No agregar dependencias nuevas sin autorizacion explicita.

## 3. Estado Actual De La Etapa 1

La Etapa 1, **Diagnostico solar**, ya esta funcional. Cubre el flujo inicial para estimar potencial solar sin depender de datos de consumo.

Componentes funcionales actuales:

- Ubicacion geografica.
- Fuente solar.
- Cielo despejado con pvlib Ineichen.
- NASA POWER.
- NASA POWER provisional 2026.
- CSV propio.
- Sistema FV.
- Orientacion.
- Resultados solares.
- Escenarios de produccion.
- Grafica diaria GHI, DNI y DHI.
- Recomendacion de inclinacion basada en coordenadas.
- Azimuth modificable.

Reglas ya establecidas para esta etapa:

- La orientacion no debe invalidar NASA POWER.
- NASA POWER usa estado durable separado de widgets condicionales.
- Las explicaciones largas en resultados deben estar en expanders.
- La grafica de barras de escenarios de produccion anual fue eliminada.
- El diseno de resultados debe mantenerse compacto.
- No debe mostrarse HTML como texto en pantalla.

## 4. Arquitectura Progresiva Del Producto

### Seccion 1: Vista Rapida - Diagnostico Climatico

**Estado:** siempre visible. Disenada para consultas rapidas.

**Entrada:**

- Ubicacion geografica mediante coordenadas, mapa o selector de ciudades.
- Inclinacion del panel.
- Orientacion o azimuth.

**Salida:**

- Grafica instantanea de irradiancia GHI, DNI y DHI para un dia seleccionado o tipico.
- Estimacion rapida de produccion fotovoltaica.
- Orientacion recomendada segun coordenadas.
- Comparacion de produccion al modificar inclinacion y azimuth.

**Notas:**

- Esta seccion no debe depender de datos de consumo.
- Debe mantenerse ligera, rapida y visual.
- Debe ser util incluso si el usuario solo quiere conocer el potencial solar de una ubicacion.

### Seccion 2: Perfil De Demanda, Balance Solar Y Modulo Express

**Estado:** condicional. Se activa cuando el usuario decide ingresar datos de consumo.

**Entrada del modulo de consumo:**

- Promedio mensual estimado.
- Historico detallado en tabla, por ejemplo a partir de recibos CFE.

**Entrada del modulo solar:**

- Cantidad de paneles.
- Potencia nominal en kW a instalar.
- Debe poder iniciar en 0 por default.

**Entrada opcional del calculo express:**

- Campo activable para ingresar costo promedio por kWh.
- Si se activa, permite estimar impacto economico simple sin desglose tarifario formal.

**Salida:**

- Comparacion entre demanda y generacion solar real.
- Balance energetico neto anual.
- Estimacion de consumo cubierto por el sistema FV.
- Si el modulo express esta activo:
  1. Cuanto paga actualmente al ano por energia.
  2. Cuanto pagaria instalando los paneles seleccionados.

**Notas:**

- Este modulo debe seguir siendo mas simple que el analisis tarifario formal.
- El objetivo es dar una estimacion rapida de ahorro y balance solar.

### Seccion 3: Ingenieria De Resiliencia Ante Apagones

**Estado:** condicional. Se activa cuando el usuario cambia el valor inicial de horas de respaldo desde 0.

**Entrada:**

- Horas de respaldo deseadas, por ejemplo de 1 a 24 horas.
- Potencia de la carga critica a proteger en kW o kVA.
- Puede aplicar a cargas industriales o residenciales criticas.

**Salida:**

- Capacidad requerida del banco de baterias en kWh.
- Propuesta automatica de sistema BESS.
- Considerar tecnologia LiFePO4 como referencia.
- Incluir expectativa de vida aproximada de 4,000 a 5,000 ciclos si se usa como supuesto.

**Notas:**

- Esta seccion debe enfocarse en continuidad operativa.
- El usuario debe entender cuanto respaldo necesita y que tamano de bateria requeriria.
- No debe saturar la vista rapida.

### Seccion 4: Evaluacion Financiera De Continuidad De Negocio

**Estado:** condicional. Se despliega si el usuario solicita analisis avanzado de rentabilidad.

**Entrada:**

- Monto historico anual asociado a danos, reparaciones, perdidas operativas o costos por apagones.
- Cotizacion comercial de baterias o sistema BESS, si esta disponible.
- Costos evitados por continuidad operativa.

**Salida:**

- Analisis de retorno de inversion basado en perdidas operativas evitadas.
- Evaluacion del costo de la inaccion.
- Simulacion de cashflow mensual con y sin paneles.
- Comparacion financiera del escenario base contra el escenario con sistema solar y respaldo.

**Notas:**

- La rentabilidad no debe limitarse al ahorro electrico.
- Debe considerar continuidad de negocio, resiliencia y perdidas evitadas.
- El enfoque debe ser formal y empresarial.

## 5. Modulo Opcional De Facturacion Precargado CFE

Este modulo existe como roadmap opcional.

Si el usuario decide realizar un desglose formal en lugar del modulo express, la interfaz debe contar con un menu desplegable para evaluar el impacto economico segun tarifa especifica. El motor debe cruzar automaticamente consumos con estructuras tarifarias precargadas.

### A. Tarifa Industrial GDMTO Coatepec, Veracruz

- Precargar variables de ejemplo como cargos fijos y proporcionales.
- Usar datos base de recibo real de referencia, por ejemplo Stteger, mayo 2026.
- Permitir estimar costo base para proyeccion anual.
- Permitir costo promedio por kWh por mes si se usa una aproximacion.

### B. Tarifas Residenciales Tipo 1

El resto del consumo acumulado residencial se considera excedente.

| Tarifa | Basico | Intermedio | Verano Int. 1 | Verano Int. 2 | Limite DAC |
|---|---:|---:|---:|---:|---:|
| 1A | 150 kWh | 150 kWh | 200 kWh | No aplica | 350 kWh |
| 1B | 150 kWh | 250 kWh | 250 kWh | 200 kWh | 800 kWh |
| 1C | 150 kWh | 250 kWh | 300 kWh | 300 kWh | 1,700 kWh |
| 1D | 150 kWh | 250 kWh | 450 kWh | 400 kWh | 2,000 kWh |
| 1E | 150 kWh | 350 kWh | 600 kWh | 600 kWh | 5,000 kWh |
| 1F | 150 kWh | 450 kWh | 1,800 kWh | 2,600 kWh | 5,000 kWh |

## 6. Reglas Tecnicas Permanentes

- No cambiar formulas sin autorizacion explicita.
- No modificar NASA POWER si la tarea no lo requiere.
- No tocar motores no relacionados con la tarea solicitada.
- No tocar demanda, tarifa, balance ni exportaciones si la tarea no lo pide.
- No agregar dependencias nuevas sin justificar.
- No usar emojis.
- No mostrar JSON al usuario.
- No mostrar HTML como texto.
- Todo HTML debe renderizarse correctamente o evitarse.
- Preferir Streamlit nativo para elementos interactivos.
- Mantener `st.plotly_chart` con keys unicas y estables.
- Mantener estado durable para NASA POWER.
- No usar keys de widgets condicionales como fuente de verdad del modelo.

## 7. Reglas Especificas De NASA POWER

- NASA POWER aporta GHI, DNI, DHI, temperatura y viento.
- La orientacion del panel no debe invalidar NASA POWER.
- Cambiar tilt, azimuth, albedo, modelo POA, paneles, potencia o perdidas no debe invalidar NASA.
- NASA solo debe invalidarse por cambios climaticos o geograficos reales: latitud, longitud, zona horaria, ano, modo NASA, ano climatico, ano base o fuente seleccionada.
- NASA provisional 2026 debe usar datos disponibles de 2026 y completar faltantes con patron climatico 2025.
- La tabla final provisional debe tener timestamps del ano de simulacion.
- La validacion debe hacerse sobre la tabla final ensamblada, no sobre datos crudos incompletos.

## 8. Flujo De Trabajo Recomendado Para Futuros Chats De Codex

- Al iniciar un nuevo chat, leer este archivo primero.
- Antes de implementar una nueva etapa, auditar lo que ya existe.
- Proponer plan de implementacion por pasos.
- No modificar codigo durante la auditoria inicial.
- Trabajar por tareas acotadas.
- Evitar cambios masivos no solicitados.
- Entregar siempre un resumen breve de archivos modificados y validaciones.

## 9. Validaciones Estandar

Para cambios en `app.py` o `src`, ejecutar:

```bash
python -m py_compile app.py
python -m pytest -q -p no:cacheprovider
```

Para cambios solo de documentacion, no es obligatorio ejecutar pytest. En ese caso se debe confirmar que no se modifico codigo funcional.

