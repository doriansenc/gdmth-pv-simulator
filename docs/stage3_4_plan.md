# Plan de arquitectura Etapas 3 y 4: Respaldo y Rentabilidad

## Actualización vigente: Etapa 3 Respaldo

La Etapa 3 calcula la recomendación BESS y el uso anual del respaldo desde el motor puro `src/backup_engine.py`. La interfaz se mantiene como wizard compacto y no mezcla ROI ni evaluación financiera dentro de Respaldo.

Puntos corregidos:

- La autonomía visible ya no se interpreta solo desde la capacidad nominal requerida; se calcula como autonomía real instalada con el número entero de baterías recomendado.
- Las horas anuales sin red se conservan como exposición operativa.
- Las horas anuales respaldadas se limitan por `min(duración_promedio_apagón, autonomía_real_instalada)`.
- La energía anual respaldada se calcula con horas respaldadas reales.
- Las horas no cubiertas distinguen faltante promedio anual y faltante ante apagón largo.
- Los ciclos equivalentes usan energía anual respaldada sobre energía útil instalada.
- Si el cálculo falla, las keys `stage3_result_*` se limpian para evitar que Rentabilidad lea resultados obsoletos.
- Las tarjetas `metric_card` escapan textos antes de renderizar HTML interno.

Fórmulas implementadas:

```text
installed_backup_hours =
    usable_installed_energy_kwh / critical_load_kw

annual_outage_hours =
    annual_outage_events * average_outage_duration_h

backed_hours_per_event =
    min(average_outage_duration_h, installed_backup_hours)

annual_backed_hours =
    annual_outage_events * backed_hours_per_event

annual_backed_energy_kwh =
    critical_load_kw * annual_backed_hours

uncovered_average_outage_hours =
    max(average_outage_duration_h - installed_backup_hours, 0)

annual_uncovered_hours =
    annual_outage_events * uncovered_average_outage_hours

long_outage_uncovered_hours =
    max(typical_max_outage_duration_h - installed_backup_hours, 0)

average_outage_covered =
    installed_backup_hours >= average_outage_duration_h

long_outage_covered =
    installed_backup_hours >= typical_max_outage_duration_h

equivalent_cycles_per_year =
    annual_backed_energy_kwh / usable_installed_energy_kwh
```

Alcance no modificado:

- No se modificaron Diagnóstico solar, Consumo y ahorro, NASA POWER ni fórmulas solares.
- Rentabilidad solo lee referencias compatibles de Respaldo y mantiene captura manual.

## 1. Objetivo de la Etapa 3: Respaldo

Construir una pestana guiada para dimensionar un sistema basico de respaldo energetico con BESS, usando tecnologia LiFePO4 como referencia y entradas compactas que el usuario pueda entender sin convertir la vista en una pagina larga.

La etapa debe responder:

- que potencia critica se va a proteger
- cuantas horas de respaldo se desean
- que capacidad util y nominal de bateria se requiere
- que recomendacion basica de BESS se obtiene
- que supuestos tecnicos explican el resultado

Alcance permitido:

- horas deseadas de respaldo
- potencia de carga critica en kW o kVA
- factor de potencia cuando la entrada sea kVA
- eficiencia del sistema
- profundidad de descarga
- margen de seguridad
- referencia LiFePO4
- vida de referencia aproximada de 4,000 a 5,000 ciclos como supuesto informativo

Fuera de alcance por ahora:

- ROI
- cashflow
- costo de inaccion
- cotizaciones complejas
- deuda, inflacion, depreciacion o impuestos
- analisis financiero avanzado

## 2. Objetivo de la Etapa 4: Rentabilidad

Construir una pestana guiada para evaluar si la inversion en respaldo y solar se justifica por continuidad operativa, usando un analisis simple y entendible.

La etapa debe responder:

- cuanto pierde anualmente el usuario por apagones, reparaciones o danos
- que monto anual podria evitarse con continuidad operativa
- cual es la inversion estimada del sistema
- cual es el periodo simple de recuperacion
- cual es el ROI simple
- como interpretar el resultado

Alcance permitido:

- perdidas anuales estimadas por apagones
- costos de reparacion o danos
- horas de paro operativo
- costo de la inaccion
- costo estimado o cotizacion del sistema BESS
- resultados previos de FV y respaldo cuando existan

Fuera de alcance por ahora:

- simulacion financiera compleja
- deuda
- inflacion
- depreciacion
- impuestos
- valuacion avanzada

## 3. Estado actual encontrado

### 3.1 Pestañas en `app.py`

`app.py` ya contiene cinco pestanas principales:

- Diagnostico solar
- Consumo y ahorro
- Respaldo
- Rentabilidad
- Avanzado

Las pestanas `Respaldo` y `Rentabilidad` existen. `Respaldo` ya esta implementado como wizard operativo; `Rentabilidad` tambien cuenta con wizard de evaluacion simple y conserva dependencia opcional de los resultados tecnicos de Respaldo.

Estado de `Respaldo`:

- Se renderiza dentro de `with tab_backup:`.
- Usa `section_header("Respaldo", ...)`.
- Usa `render_stage3_backup_wizard()` como wizard interno progresivo.
- Captura carga critica, historial de apagones, supuestos BESS y resultados.
- Usa `src/backup_engine.py` como motor puro para dimensionamiento y uso anual.
- Calcula capacidad nominal requerida, baterias recomendadas, energia util instalada, autonomia real instalada, horas respaldadas, horas no cubiertas, energia anual respaldada, ciclos equivalentes y cobertura de apagones largos.
- Escribe resultados derivados en keys `stage3_result_*` para lectura opcional desde Rentabilidad.
- Limpia resultados previos si el calculo falla para evitar referencias obsoletas.

Estado de `Rentabilidad`:

- Se renderiza dentro de `with tab_profitability:`.
- Usa `section_header("Rentabilidad", ...)`.
- Usa `render_stage4_profitability_wizard(summary)` como wizard interno progresivo.
- Usa `src/profitability_engine.py` como motor puro para costo de inaccion, inversion, recuperacion simple y ROI simple.
- Lee referencias opcionales de Respaldo y Consumo y ahorro cuando existen, sin bloquear captura manual.
- Escribe resultados derivados en keys `stage4_result_*`.
- Mantiene la evaluacion en rentabilidad simple, sin cashflow avanzado.

Textos actuales que deben mantenerse corregidos:

- Los textos de `Respaldo` ya no deben tratar el modulo como placeholder.
- La UI de `Respaldo` debe diferenciar horas sin red, horas respaldadas, energia anual respaldada y horas no cubiertas.
- Los textos de `Rentabilidad` ya no deben tratar el modulo como placeholder.
- La UI de `Rentabilidad` debe presentar beneficio anual, recuperacion simple y ROI simple sin prometer analisis financiero avanzado.

### 3.2 Patron vigente de wizard progresivo

La Etapa 2 ya esta implementada con un patron reutilizable:

- lista de pasos `STAGE2_STEPS`
- key durable `stage2_step`
- botones de progreso por paso
- navegacion anterior/siguiente
- funciones de render por paso
- keys durables separadas de keys temporales de widgets
- contexto compacto al final del wizard

El mismo enfoque debe usarse para Etapa 3 y Etapa 4, sin mover logica de Etapa 1 ni Etapa 2.

### 3.3 Modulos existentes relacionados

Modulos especificos ya disponibles:

- `src/backup_engine.py`: calcula dimensionamiento BESS, autonomia real instalada, energia anual respaldada, horas no cubiertas y ciclos equivalentes.
- `src/profitability_engine.py`: calcula costo de inaccion, inversion estimada, beneficio anual, recuperacion simple y ROI simple.

Aspectos que siguen fuera de alcance:

- cashflow dedicado
- deuda
- inflacion
- depreciacion
- impuestos
- valuacion financiera avanzada

Modulos existentes que si pueden aportar datos o patrones:

- `src/summary.py`: expone generacion FV anual, demanda anual, autoconsumo, energia de red, exportacion, cobertura, pico de generacion y pico de demanda.
- `src/express_savings.py`: calcula ahorro express anual con consumo, generacion FV y costo promedio por kWh.
- `src/receipt_savings.py`: calcula ahorro con datos de recibo y precio medio facturado; no incluye ROI ni BESS.
- `src/tariff_engine.py`: calcula estimacion GDMTH, costos con/sin FV y ahorro; debe mantenerse separado de la rentabilidad simple.
- `src/demand_engine.py`: contiene demanda sintetica/real y balance energetico, util solo como referencia de potencia y demanda.
- `src/ui_components.py`: contiene `section_header` y `metric_card`, utiles para conservar consistencia visual.

## 4. Wizard propuesto para Etapa 3: Respaldo

Pasos internos recomendados:

1. Carga critica
2. Horas de respaldo
3. Sistema BESS
4. Resultados

La pestana debe ser formal, compacta y progresiva. Cada paso debe tener pocas entradas visibles y resultados preliminares en metricas.

### 4.1 Paso: Carga critica

Objetivo:

- Definir la potencia critica que el sistema debe sostener.

Entradas:

- modo de entrada de potencia: `kW` o `kVA`
- potencia de carga critica
- factor de potencia, visible o habilitado cuando el modo sea `kVA`
- nota compacta opcional sobre cargas criticas

Salidas:

- potencia critica considerada en kW
- potencia aparente de referencia en kVA, si aplica
- estado de validez de la carga

Keys durables propuestas:

- `stage3_step`
- `stage3_critical_load_input_mode`
- `stage3_critical_load_kw`
- `stage3_critical_load_kva`
- `stage3_power_factor`

Keys temporales de widget propuestas:

- `_stage3_critical_load_input_mode_widget`
- `_stage3_critical_load_kw_widget`
- `_stage3_critical_load_kva_widget`
- `_stage3_power_factor_widget`

Validaciones:

- potencia critica mayor o igual a cero
- factor de potencia mayor que cero y menor o igual a uno
- si la entrada esta en kVA, convertir a kW con `critical_load_kw = critical_load_kva * power_factor`
- si la potencia critica es cero, mostrar estado pendiente sin bloquear la pestana

### 4.2 Paso: Horas de respaldo

Objetivo:

- Definir la autonomia deseada del respaldo.

Entradas:

- horas de respaldo deseadas
- opcion compacta de usar valor recomendado o manual

Salidas:

- energia critica util requerida antes de perdidas
- vista preliminar `kW x h`

Keys durables propuestas:

- `stage3_backup_hours`
- `stage3_backup_hours_mode`

Keys temporales de widget propuestas:

- `_stage3_backup_hours_widget`
- `_stage3_backup_hours_mode_widget`

Validaciones:

- horas mayor o igual a cero
- rango sugerido inicial de 0 a 24 horas
- si horas es cero, mantener la pestana usable pero marcar resultados como pendientes

### 4.3 Paso: Sistema BESS

Objetivo:

- Capturar supuestos de bateria y sistema sin entrar en cotizacion.

Entradas:

- tecnologia de referencia, por default `LiFePO4`
- eficiencia del sistema
- profundidad de descarga
- margen de seguridad
- potencia nominal recomendada editable o derivada de la carga critica

Salidas:

- energia util requerida
- capacidad nominal requerida
- potencia BESS minima recomendada
- texto compacto de supuestos

Keys durables propuestas:

- `stage3_battery_technology`
- `stage3_system_efficiency`
- `stage3_depth_of_discharge`
- `stage3_safety_margin`
- `stage3_bess_power_kw`

Keys temporales de widget propuestas:

- `_stage3_battery_technology_widget`
- `_stage3_system_efficiency_widget`
- `_stage3_depth_of_discharge_widget`
- `_stage3_safety_margin_widget`
- `_stage3_bess_power_kw_widget`

Validaciones:

- eficiencia mayor que cero y menor o igual a uno
- profundidad de descarga mayor que cero y menor o igual a uno
- margen de seguridad mayor o igual a cero
- potencia BESS mayor o igual a la carga critica cuando exista carga valida

### 4.4 Paso: Resultados

Objetivo:

- Presentar la recomendacion BESS de forma ejecutiva.

Salidas visibles:

- capacidad requerida del banco de baterias en kWh
- potencia critica considerada
- horas de respaldo cubiertas
- autonomia real instalada segun numero entero de baterias
- horas anuales sin red, respaldadas y no cubiertas
- energia anual efectivamente respaldada
- ciclos equivalentes calculados con energia anual respaldada
- recomendacion basica del sistema BESS
- explicacion compacta de supuestos

Componentes sugeridos:

- filas compactas de `metric_card` o `st.metric`
- un contenedor breve con la recomendacion
- un expander cerrado por default para formulas y supuestos

Keys durables de resultado propuestas:

- `stage3_result_critical_load_kw`
- `stage3_result_backup_hours`
- `stage3_result_required_usable_kwh`
- `stage3_result_required_nominal_kwh`
- `stage3_result_required_bess_capacity_kwh`
- `stage3_result_installed_backup_hours`
- `stage3_result_annual_outage_events`
- `stage3_result_annual_outage_hours`
- `stage3_result_annual_backed_hours`
- `stage3_result_annual_backed_energy_kwh`
- `stage3_result_uncovered_average_outage_hours`
- `stage3_result_annual_uncovered_hours`
- `stage3_result_equivalent_cycles_per_year`
- `stage3_result_estimated_life_years_by_cycles`
- `stage3_result_long_outage_uncovered_hours`
- `stage3_result_long_outage_covered`
- `stage3_result_recommended_battery_count`
- `stage3_result_total_installed_capacity_kwh`
- `stage3_result_usable_installed_energy_kwh`
- `stage3_result_is_complete`

Nota de implementacion:

- Estos resultados pueden calcularse al vuelo desde las entradas durables.
- Solo conviene guardar resultados en `session_state` si Rentabilidad los va a leer como referencia compacta.

## 5. Funciones puras de Etapa 3

La Etapa 3 usa el modulo separado `src/backup_engine.py`.

Funciones principales:

- `calculate_bess_backup(...) -> dict`
- `interpret_cycle_life(...) -> dict`

Formulas implementadas:

```text
critical_load_kw = critical_load_kw_input
critical_load_kw = critical_load_kva * power_factor

usable_energy_kwh = critical_load_kw * backup_hours

nominal_battery_kwh =
    usable_energy_kwh * (1 + safety_margin) / (system_efficiency * depth_of_discharge)

recommended_bess_power_kw = max(critical_load_kw, manual_bess_power_kw)

covered_hours =
    nominal_battery_kwh * system_efficiency * depth_of_discharge / critical_load_kw

recommended_battery_count =
    ceil(nominal_battery_kwh / battery_capacity_kwh)

total_installed_capacity_kwh =
    recommended_battery_count * battery_capacity_kwh

usable_installed_energy_kwh =
    total_installed_capacity_kwh * depth_of_discharge * system_efficiency

installed_backup_hours =
    usable_installed_energy_kwh / critical_load_kw

annual_outage_hours =
    annual_outage_events * average_outage_duration_h

backed_hours_per_event =
    min(average_outage_duration_h, installed_backup_hours)

annual_backed_hours =
    annual_outage_events * backed_hours_per_event

annual_backed_energy_kwh =
    critical_load_kw * annual_backed_hours

uncovered_average_outage_hours =
    max(average_outage_duration_h - installed_backup_hours, 0)

annual_uncovered_hours =
    annual_outage_events * uncovered_average_outage_hours

long_outage_uncovered_hours =
    max(typical_max_outage_duration_h - installed_backup_hours, 0)

equivalent_cycles_per_year =
    annual_backed_energy_kwh / usable_installed_energy_kwh
```

Condiciones de seguridad:

- Si `critical_load_kw <= 0`, `covered_hours` debe ser cero o `None`.
- Si eficiencia o profundidad de descarga son cero, no dividir; devolver error de validacion.
- El margen debe aplicarse sobre la energia util requerida antes de convertir a capacidad nominal.
- La energia anual respaldada debe limitarse a la autonomia real instalada; no debe usar todas las horas anuales sin red si la duracion promedio del apagón supera la autonomia disponible.
- La cobertura de apagón promedio y largo debe evaluarse contra `installed_backup_hours`, no contra las horas deseadas nominales.

## 6. Wizard propuesto para Etapa 4: Rentabilidad

Pasos internos recomendados:

1. Costo de inaccion
2. Inversion estimada
3. Evaluacion
4. Resultados

La pestana debe permitir avanzar aunque Respaldo no este completo. Si hay resultados de Etapa 3, debe usarlos como referencia; si no, debe permitir datos manuales.

### 6.1 Paso: Costo de inaccion

Objetivo:

- Capturar el impacto economico anual de apagones y continuidad operativa.

Entradas:

- perdidas anuales estimadas por apagones
- costos anuales de reparacion o danos
- horas anuales de paro operativo
- costo promedio por hora de paro
- porcentaje estimado de perdidas evitables

Salidas:

- costo anual de paro calculado
- costo anual de inaccion
- perdidas anuales evitables

Keys durables propuestas:

- `stage4_step`
- `stage4_annual_outage_losses_mxn`
- `stage4_annual_repair_costs_mxn`
- `stage4_downtime_hours_per_year`
- `stage4_downtime_cost_mxn_per_hour`
- `stage4_avoidable_loss_percent`

Keys temporales de widget propuestas:

- `_stage4_annual_outage_losses_mxn_widget`
- `_stage4_annual_repair_costs_mxn_widget`
- `_stage4_downtime_hours_per_year_widget`
- `_stage4_downtime_cost_mxn_per_hour_widget`
- `_stage4_avoidable_loss_percent_widget`

Validaciones:

- todos los costos mayores o iguales a cero
- horas de paro mayores o iguales a cero
- porcentaje evitable entre cero y cien
- si todo es cero, mostrar resultado pendiente sin bloquear

### 6.2 Paso: Inversion estimada

Objetivo:

- Definir la inversion del sistema que se evaluara.

Entradas:

- modo de inversion: manual o referencia desde Respaldo
- costo estimado o cotizacion BESS
- costo estimado FV opcional, si se quiere evaluar solar + respaldo
- otros costos directos opcionales
- referencia de capacidad BESS calculada, si existe

Salidas:

- inversion estimada total
- referencia tecnica usada
- advertencia si no hay cotizacion ni costo manual

Keys durables propuestas:

- `stage4_investment_mode`
- `stage4_bess_cost_mxn`
- `stage4_pv_cost_mxn`
- `stage4_other_costs_mxn`
- `stage4_use_stage3_reference`

Keys temporales de widget propuestas:

- `_stage4_investment_mode_widget`
- `_stage4_bess_cost_mxn_widget`
- `_stage4_pv_cost_mxn_widget`
- `_stage4_other_costs_mxn_widget`
- `_stage4_use_stage3_reference_widget`

Validaciones:

- inversiones mayores o iguales a cero
- permitir inversion manual aunque no exista Respaldo
- si hay capacidad BESS de Etapa 3, mostrarla como referencia, no como dependencia obligatoria

### 6.3 Paso: Evaluacion

Objetivo:

- Calcular beneficio anual simple, payback y ROI simple.

Entradas:

- beneficio anual por continuidad, derivado del costo evitable
- ahorro FV previo si existe y si se decide incluirlo como referencia
- inversion estimada total

Salidas:

- beneficio anual estimado
- periodo simple de recuperacion
- ROI simple anual
- interpretacion preliminar

Keys durables propuestas:

- `stage4_include_pv_savings_reference`
- `stage4_manual_annual_benefit_mxn`
- `stage4_benefit_mode`

Keys temporales de widget propuestas:

- `_stage4_include_pv_savings_reference_widget`
- `_stage4_manual_annual_benefit_mxn_widget`
- `_stage4_benefit_mode_widget`

Validaciones:

- beneficio anual mayor o igual a cero
- si inversion es cero, no calcular payback artificial; mostrar pendiente
- si beneficio anual es cero, payback no disponible y ROI cero

### 6.4 Paso: Resultados

Objetivo:

- Mostrar una lectura ejecutiva de rentabilidad simple.

Salidas visibles:

- perdidas anuales evitables
- inversion estimada
- ahorro o beneficio anual estimado
- periodo simple de recuperacion
- ROI simple
- interpretacion del resultado

Componentes sugeridos:

- fila de metricas compactas
- interpretacion en un contenedor breve
- expander cerrado para formulas y supuestos
- mensaje de estado si faltan datos minimos

Keys durables de resultado propuestas:

- `stage4_result_avoidable_losses_mxn`
- `stage4_result_total_investment_mxn`
- `stage4_result_annual_benefit_mxn`
- `stage4_result_simple_payback_years`
- `stage4_result_simple_roi_percent`
- `stage4_result_is_complete`

## 7. Funciones puras de Etapa 4

La Etapa 4 usa el modulo separado `src/profitability_engine.py`.

Funciones principales:

- `calculate_profitability(...) -> dict`
- `percent_to_fraction(...) -> float`

Formulas implementadas:

```text
downtime_cost_mxn =
    downtime_hours_per_year * downtime_cost_mxn_per_hour

inaction_cost_mxn =
    annual_outage_losses_mxn + annual_repair_costs_mxn + downtime_cost_mxn

avoidable_losses_mxn =
    inaction_cost_mxn * avoidable_loss_percent / 100

total_investment_mxn =
    bess_cost_mxn + pv_cost_mxn + other_costs_mxn

annual_benefit_mxn =
    avoidable_losses_mxn + optional_pv_savings_reference_mxn

simple_payback_years =
    total_investment_mxn / annual_benefit_mxn

simple_roi_percent =
    annual_benefit_mxn / total_investment_mxn * 100
```

Condiciones de seguridad:

- Si `total_investment_mxn <= 0`, payback y ROI deben quedar como no disponibles.
- Si `annual_benefit_mxn <= 0`, payback debe quedar como no disponible y ROI en cero si hay inversion.
- No incluir deuda, inflacion, depreciacion, impuestos ni valor presente.

## 8. Relacion entre etapas

Rentabilidad debe poder usar resultados de Respaldo, pero no debe depender de que Respaldo este completo.

Comportamiento recomendado:

- Si existe `stage3_result_required_nominal_kwh`, mostrarlo como referencia de capacidad BESS.
- Si existe `stage3_result_recommended_battery_count`, mostrarlo como referencia de cantidad de baterias.
- Si existe `stage3_result_total_installed_capacity_kwh`, mostrarlo como referencia de capacidad instalada.
- Si `stage3_result_is_complete` es verdadero, habilitar una opcion de usar referencia tecnica de Respaldo.
- Si Respaldo no esta completo, permitir capturar inversion BESS manual.
- No bloquear Rentabilidad por falta de horas de respaldo, carga critica o capacidad BESS.
- No recalcular formulas de Respaldo dentro de Rentabilidad; leer resultados o entradas durables como referencia.

Referencias de Etapa 2 que Rentabilidad podria usar despues:

- ahorro express anual de `compute_express_savings(...)`, si el usuario lo activo y tiene costo promedio valido
- ahorro basado en recibo de `compute_receipt_based_savings(...)`, si existe analisis avanzado capturado
- ahorro GDMTH actual, solo si se decide exponerlo explicitamente como referencia y sin cambiar formulas existentes

Regla de desacoplamiento:

- Etapa 4 debe funcionar con datos manuales aunque Etapa 2 y Etapa 3 esten incompletas.

## 9. Entradas y salidas resumidas

### Etapa 3: Respaldo

Entradas:

- potencia critica en kW o kVA
- factor de potencia si aplica
- horas de respaldo
- tecnologia de referencia
- eficiencia del sistema
- profundidad de descarga
- margen de seguridad
- potencia BESS recomendada o manual

Salidas:

- potencia critica considerada en kW
- energia util requerida en kWh
- capacidad nominal requerida en kWh
- potencia minima recomendada del BESS
- horas de respaldo cubiertas
- autonomia real instalada
- horas anuales sin red
- horas anuales respaldadas
- horas anuales no cubiertas
- energia anual respaldada limitada por autonomia instalada
- ciclos equivalentes por año
- cobertura o faltante de apagón largo
- explicacion compacta de supuestos

### Etapa 4: Rentabilidad

Entradas:

- perdidas anuales por apagones
- costos de reparacion o danos
- horas anuales de paro operativo
- costo por hora de paro
- porcentaje de perdidas evitables
- costo BESS
- costo FV opcional
- otros costos directos
- referencias opcionales de FV y Respaldo

Salidas:

- costo anual de inaccion
- perdidas anuales evitables
- inversion estimada
- beneficio anual estimado
- periodo simple de recuperacion
- ROI simple
- interpretacion del resultado

## 10. Riesgos tecnicos

- Mezclar ROI dentro de Respaldo romperia el alcance de Etapa 3.
- Hacer depender Rentabilidad de Respaldo bloquearia usuarios que solo tienen una cotizacion manual.
- Guardar resultados derivados como unica fuente de verdad podria causar datos obsoletos al cambiar entradas.
- Usar keys condicionales de widgets como fuente de verdad repetiria problemas de resets al navegar.
- Incluir ahorro GDMTH automaticamente en ROI puede mezclar niveles de analisis y formulas existentes.
- Calcular kVA sin factor de potencia valido puede subestimar o sobreestimar la carga critica.
- Usar profundidad de descarga o eficiencia en cero puede producir divisiones invalidas.
- Mostrar demasiadas tablas o explicaciones convertiria las pestanas en paginas largas.
- Agregar costos unitarios BESS por kWh sin una fuente clara podria parecer cotizacion formal.
- Modificar `run_simulation()`, NASA POWER, Etapa 1 o Etapa 2 no es necesario para estas etapas.

## 11. Pruebas recomendadas

Cuando se implemente codigo, ejecutar:

```bash
python -m py_compile app.py
python -m pytest -q -p no:cacheprovider
```

Pruebas unitarias recomendadas para Respaldo:

- entrada kW conserva potencia critica
- entrada kVA convierte con factor de potencia
- energia util es potencia critica por horas
- capacidad nominal aplica eficiencia, profundidad de descarga y margen
- autonomia real instalada usa energia util instalada dividida entre carga critica
- energia anual respaldada usa horas respaldadas reales, no horas anuales sin red completas cuando el apagón promedio supera la autonomia instalada
- duracion promedio menor o igual a autonomia instalada queda completamente cubierta
- duracion promedio mayor que autonomia instalada genera horas no cubiertas por evento y anuales
- apagón largo se evalua contra autonomia instalada y reporta horas faltantes
- ciclos equivalentes usan energia anual respaldada dividida entre energia util instalada
- horas cubiertas no divide entre cero
- entradas negativas generan error de validacion
- eficiencia cero o profundidad de descarga cero generan error de validacion
- resultados permanecen en cero o pendientes con carga cero u horas cero
- resultados `stage3_result_*` obsoletos se limpian cuando el calculo falla
- `metric_card` escapa textos editables para evitar HTML visible o inyeccion de marcado

Pruebas unitarias recomendadas para Rentabilidad:

- costo de paro es horas por costo horario
- costo de inaccion suma perdidas, reparaciones y paro
- perdidas evitables aplican porcentaje correctamente
- inversion total suma BESS, FV y otros costos
- payback simple divide inversion entre beneficio anual
- ROI simple divide beneficio anual entre inversion
- inversion cero no produce ROI artificial
- beneficio cero no produce payback invalido
- Rentabilidad funciona sin resultados de Respaldo
- Rentabilidad usa referencia de Respaldo cuando existe sin bloquear entrada manual

Pruebas de interfaz recomendadas:

- cada wizard conserva el paso activo al navegar
- las keys durables sobreviven cambios entre pasos
- los placeholders actuales desaparecen al implementar cada wizard
- las pestanas siguen siendo compactas en desktop
- los expanders de formulas inician cerrados
- Diagnostico solar y Consumo y ahorro no cambian

## 12. Secuencia de implementacion documentada

1. `src/backup_engine.py` contiene funciones puras y pruebas unitarias para Respaldo.
2. `DEFAULT_STATE` incluye defaults durables de `stage3_*` y `stage3_result_*`.
3. `STAGE3_STEPS` y helpers de navegacion siguen el patron de Etapa 2.
4. `Respaldo` se renderiza con `render_stage3_backup_wizard(...)`.
5. Los resultados compactos de Respaldo quedan disponibles para uso opcional en Rentabilidad.
6. `src/profitability_engine.py` contiene funciones puras y pruebas unitarias para Rentabilidad.
7. `DEFAULT_STATE` incluye defaults durables de `stage4_*`.
8. `STAGE4_STEPS` y helpers de navegacion siguen el patron de Etapa 2.
9. `Rentabilidad` se renderiza con `render_stage4_profitability_wizard(...)`.
10. Las referencias opcionales de Respaldo y FV no son obligatorias.
11. Las validaciones estandar deben ejecutarse despues de cada ajuste relevante.
12. La revision visual debe confirmar pestanas formales, compactas y progresivas.

## 13. Confirmacion de alcance de la auditoria original

Esta seccion documenta el alcance de la auditoria y planeacion original, antes de implementar Etapa 3 y Etapa 4. La implementacion posterior queda documentada en las secciones siguientes.

No se implementaron funciones nuevas.
No se cambio la interfaz.
No se modifico `app.py`.
No se modifico `src`.
No se cambiaron formulas existentes.
No se cambio NASA POWER.
No se cambio Etapa 1.
No se cambio Etapa 2.
No se agregaron dependencias.

## 14. Actualización de implementación: Etapa 4 Rentabilidad

La Etapa 4 queda preparada como wizard interno progresivo dentro de la pestaña `Rentabilidad`.

Objetivo implementado:

- Evaluar si la inversión estimada en BESS, y opcionalmente FV, se justifica por continuidad operativa.
- Mantener el análisis en recuperación simple y ROI simple, sin flujo de caja avanzado.
- Usar resultados previos de Respaldo y Consumo y ahorro como referencias opcionales, sin bloquear captura manual.

Estructura implementada del wizard:

1. Costo de inacción
   - Entradas: apagones al año, horas anuales sin red, costo por hora sin operación, costo fijo por apagón, reparaciones o daños anuales, porcentaje de pérdidas evitables.
   - Salidas: costo anual de inacción y pérdidas anuales evitables.

2. Inversión estimada
   - Entradas: baterías consideradas, costo unitario por batería, complemento del sistema por porcentaje o monto manual, inversión FV opcional.
   - Salidas: costo de baterías, costo complementario, inversión BESS e inversión total.

3. Evaluación
   - Entradas: ahorro energético anual opcional.
   - Salidas: beneficio anual total, recuperación simple, ROI simple y costo acumulado de la inacción.

4. Resultados
   - Salidas: tarjetas compactas de inversión, pérdidas evitables, beneficio anual, recuperación simple, ROI simple y costo de inacción a 3, 5 y 10 años.
   - Gráfica: comparación acumulada de inversión, costo de inacción y beneficio estimado.
   - Expander cerrado por default: interpretación de la rentabilidad.

Módulo puro agregado:

- `src/profitability_engine.py`
- Función principal: `calculate_profitability(...)`

Fórmulas implementadas:

```text
costo_paro_anual = horas_anuales_sin_red * costo_por_hora_sin_operación
costo_eventos_anual = apagones_al_año * costo_fijo_por_apagón
costo_inacción_anual = costo_paro_anual + costo_eventos_anual + reparaciones_o_daños_anuales
pérdidas_evitables = costo_inacción_anual * porcentaje_pérdidas_evitables
costo_baterías = baterías_consideradas * costo_unitario_batería
costo_complementario = costo_baterías * porcentaje_complementario
inversión_bess = costo_baterías + costo_complementario
inversión_total = inversión_bess + inversión_fv_opcional
beneficio_anual_total = pérdidas_evitables + ahorro_energético_anual_opcional
recuperación_simple_años = inversión_total / beneficio_anual_total
roi_simple_pct = beneficio_anual_total / inversión_total * 100
```

Referencias opcionales entre etapas:

- Si Respaldo tiene apagones, horas anuales o baterías recomendadas, Rentabilidad los usa como referencia inicial.
- Si no existen resultados de Respaldo, Rentabilidad permite captura manual.
- Si Consumo y ahorro tiene ahorro anual estimado, Rentabilidad puede usarlo como referencia opcional.
- Rentabilidad no depende de que Respaldo o Consumo y ahorro estén completos.

Alcance excluido:

- No se agregó cashflow.
- No se agregó VPN, TIR ni valuación avanzada.
- No se agregó deuda, inflación, depreciación ni impuestos.
- No se modificaron NASA POWER, fórmulas solares, Etapa 1, Etapa 2 ni cálculos de Respaldo.

Pruebas agregadas:

- costo anual de inacción
- pérdidas evitables
- inversión BESS por baterías y costo unitario
- costo complementario por porcentaje
- costo complementario por monto manual
- inversión FV opcional
- ahorro energético anual opcional
- recuperación simple
- ROI simple
- protección ante beneficio anual cero
- costos de inacción a 3, 5 y 10 años
- datos de la gráfica acumulada
## 15. Ajustes de interpretación y presentación

La interfaz de Rentabilidad debe mostrar porcentajes como valores de 0 a 100 para evitar confusión operativa.

- `Pérdidas evitables [%]` se muestra como 90 por default y se convierte internamente a `0.90`.
- `Costos complementarios [%]` se muestra como 20 por default y se convierte internamente a `0.20`.
- El motor financiero conserva fracciones internas entre 0 y 1 para ambos porcentajes.
- El cálculo de complementarios se mantiene como `costo_baterías * porcentaje_decimal`.

El costo unitario de batería debe tratarse como referencia editable:

- LiFePO4 y $25,000 MXN son referencias iniciales.
- El usuario debe sustituir modelo, capacidad y costo con la ficha técnica y cotización real.
- No se deben hardcodear marcas o modelos comerciales.

La vida por ciclos en Respaldo debe presentarse como referencia teórica, no como vida real garantizada:

- Si la vida teórica por ciclos supera 25 años, se muestra `Ciclos no limitantes` y el uso en ciclos por año.
- Si la vida teórica por ciclos es menor o igual a 25 años, se muestra como `Vida teórica por ciclos`.
- En ambos casos se aclara que la vida real depende de vida calendario, garantía, temperatura, BMS y condiciones de operación.

La recuperación simple de Rentabilidad usa únicamente el beneficio anual estimado:

```text
beneficio_anual_total = pérdidas_evitables + ahorro_energético_anual_opcional
recuperación_simple = inversión_total / beneficio_anual_total
roi_simple_pct = beneficio_anual_total / inversión_total * 100
```

El costo bruto de la inacción se conserva como métrica de riesgo, pero no sustituye a las pérdidas evitables cuando la fracción evitable es menor a 100%.
