# Validacion tecnica del modelo GDMTH fotovoltaico

## Objetivo del simulador

El simulador estima el desempeno tecnico y economico de un sistema fotovoltaico conectado a una carga industrial bajo una tarifa tipo GDMTH. El objetivo es comparar, con resolucion de 15 minutos durante un ano completo, la generacion fotovoltaica, la demanda, el autoconsumo, la energia tomada de red y el costo electrico estimado con y sin sistema fotovoltaico.

El modelo esta disenado como MVP academico: prioriza consistencia fisica, trazabilidad de unidades y una aproximacion economica defendible. No sustituye un estudio oficial de interconexion, diseno electrico ni facturacion CFE.

## Flujo general del modelo

```text
Inputs de ubicacion, geometria y sistema FV
        |
        v
Indice anual de 15 minutos
        |
        v
Irradiancia GHI/DNI/DHI o cielo despejado pvlib
        |
        v
Posicion solar y transposicion POA
        |
        v
Generacion FV kW y kWh por intervalo
        |
        v
Demanda sintetica o demanda real cargada
        |
        v
Balance energetico por intervalo
        |
        v
Modulo tarifario GDMTH anual
        |
        v
Resumen tecnico, economico y graficas
```

## Inputs fisicos

Los inputs fisicos principales son:

| Grupo | Inputs |
|---|---|
| Ubicacion | latitud, longitud, altitud, zona horaria, ano |
| Irradiancia | fuente solar, GHI, DNI, DHI, temperatura ambiente, viento |
| Geometria | inclinacion `tilt_deg`, orientacion `azimuth_deg`, albedo |
| Modulo FV | potencia nominal por panel `panel_power_w`, numero de paneles, area, eficiencia |
| Perdidas | perdidas agregadas del sistema `system_losses` |
| Temperatura | coeficiente termico del panel y temperatura de celda calculada |

La potencia nominal instalada se define como:

```text
P_instalada_kWp = number_of_panels * panel_power_w / 1000
```

El area y la eficiencia del panel se conservan como informacion fisica y validacion de consistencia:

```text
estimated_panel_power_w = panel_area_m2 * panel_efficiency * 1000
```

Si la potencia estimada por area difiere mucho de la potencia nominal ingresada, el modelo genera una advertencia interna, pero la simulacion usa la potencia nominal como base.

La potencia nominal instalada y la potencia estimada por area y eficiencia son metricas STC de capacidad. No representan energia producida y no deben cambiar con nubes ni perdidas. La generacion anual simulada si cambia con irradiancia, POA, temperatura y perdidas.

## Calculo de irradiancia POA

El modelo usa `pvlib` para calcular posicion solar y transponer la irradiancia al plano del arreglo.

Fuentes de irradiancia soportadas:

- cielo despejado con modelo Ineichen de `pvlib`;
- escenario climatico simple como factor sobre cielo despejado;
- PVGIS mediante `pvlib.iotools`;
- NSRDB PSM3 mediante `pvlib.iotools` o API;
- NASA POWER;
- CSV propio.

Cuando hay datos externos con GHI pero sin DNI/DHI, se usa `pvlib.irradiance.erbs` para descomponer GHI. La irradiancia en plano del arreglo se calcula con:

```text
POA_W_m2 = pvlib.irradiance.get_total_irradiance(
    surface_tilt,
    surface_azimuth,
    solar_zenith,
    solar_azimuth,
    dni,
    ghi,
    dhi,
    albedo,
    model
)
```

Los modelos de transposicion disponibles incluyen `isotropic`, `haydavies` y `perez`.

## Ecuaciones FV

La temperatura de celda se estima con el modelo Faiman de `pvlib`:

```text
T_cell = pvlib.temperature.faiman(POA, T_air, wind_speed)
```

El factor termico se calcula como:

```text
temperature_factor = 1 + gamma * (T_cell - 25)
```

donde `gamma` es el coeficiente termico por grado Celsius. El modelo limita el factor termico para evitar resultados no fisicos extremos.

La generacion FV usa como base la potencia nominal instalada:

```text
raw_generation_kW =
    P_instalada_kWp * (POA_W_m2 / 1000) * temperature_factor

generation_kW =
    raw_generation_kW * (1 - system_losses)

energy_kWh =
    generation_kW * 0.25
```

El factor `0.25` corresponde a un intervalo de 15 minutos:

```text
15 min = 0.25 h
```

## Inputs de demanda

El simulador soporta dos modos de demanda.

### Demanda sintetica

Inputs:

| Input | Uso |
|---|---|
| `max_demand_kw` | limita la demanda maxima |
| `plant_factor` | fija la relacion promedio/pico anual |
| `power_factor` | calcula potencia aparente |
| `weekend_reduction` | reduce carga en fines de semana |
| `summer_increase` | incrementa carga en meses de verano |
| `random_seed` | hace reproducible la variabilidad |

La demanda sintetica construye una forma diaria industrial con base nocturna, rampa matutina, bloque productivo y rampa vespertina. Luego aplica factores de fin de semana, verano y ruido reproducible. Finalmente escala la forma para aproximar:

```text
mean(demand_kW) / max(demand_kW) = plant_factor
```

Las unidades se conservan con:

```text
demand_energy_kWh = demand_kW * 0.25
apparent_power_kVA = demand_kW / power_factor
```

### Demanda real cargada por archivo

El archivo puede ser CSV o Excel. Columnas minimas:

```text
datetime
demand_kW
```

Columnas opcionales:

```text
demand_energy_kWh
power_factor
```

Validaciones:

- `datetime` debe convertirse a fecha/hora;
- `demand_kW` debe ser numerico;
- `demand_kW` no puede ser negativo;
- si falta `demand_energy_kWh`, se calcula como `demand_kW * 0.25`;
- si falta `power_factor`, se usa el factor de potencia general;
- si la resolucion no es de 15 minutos, se interpola/reindexa a 15 minutos;
- si faltan intervalos, se reporta advertencia;
- si hay duplicados, se promedian por timestamp.

La salida queda compatible con el resto del simulador:

```text
datetime
demand_kW
demand_energy_kWh
apparent_power_kVA
power_factor
demand_source
```

## Balance energetico

El balance se calcula en cada intervalo de 15 minutos.

```text
self_consumed_kWh = min(energy_kWh, demand_energy_kWh)

exported_kWh = max(energy_kWh - demand_energy_kWh, 0)

grid_energy_kWh = max(demand_energy_kWh - energy_kWh, 0)

net_power_kW = generation_kW - demand_kW
```

Balances conservados:

```text
energy_kWh = self_consumed_kWh + exported_kWh

demand_energy_kWh = self_consumed_kWh + grid_energy_kWh
```

Estos balances se verifican por intervalo y en totales anuales.

## Modulo tarifario GDMTH

El modulo tarifario estima costos mensuales y anuales con y sin FV. Usa los 35,040 intervalos de la simulacion anual, agrupados por mes real.

### Inputs tarifarios

| Input | Descripcion |
|---|---|
| `base_rate_mxn_kwh` | cargo energetico periodo base |
| `intermediate_rate_mxn_kwh` | cargo energetico periodo intermedio |
| `peak_rate_mxn_kwh` | cargo energetico periodo punta |
| `distribution_rate_mxn_kw` | cargo por demanda de distribucion |
| `capacity_rate_mxn_kw` | cargo por demanda de capacidad |
| `fixed_monthly_charge_mxn` | cargo fijo mensual |
| `iva_rate` | tasa de IVA |
| `reference_power_factor` | referencia de factor de potencia, por defecto 0.90 |
| `demand_limit_load_factor` | factor usado en limite de demanda facturable, por defecto 0.57 |
| `demand_charge_enabled` | activa o desactiva cargos por demanda |

### Periodos tarifarios

La clasificacion de periodos se hace automaticamente usando timestamps reales.

Supuesto horario simplificado:

| Dia | Base | Intermedia | Punta |
|---|---|---|---|
| Lunes a viernes | 00:00-06:00 y 22:00-24:00 | resto del dia | 18:00-22:00 |
| Sabado | 00:00-08:00 y 21:00-24:00 | resto del dia | 19:00-21:00 |
| Domingo | 00:00-18:00 | 18:00-24:00 | no aplica |

Este calendario es academico y configurable en codigo; no sustituye el calendario oficial CFE por region, temporada o contrato.

### Energia por periodo

Para cada mes y escenario:

```text
base_energy_kWh = sum(energy_kWh del periodo Base)
intermediate_energy_kWh = sum(energy_kWh del periodo Intermedia)
peak_energy_kWh = sum(energy_kWh del periodo Punta)
```

Sin FV se usa `demand_energy_kWh`. Con FV se usa `grid_energy_kWh`.

```text
energy_cost =
    base_energy_kWh * base_rate_mxn_kwh
  + intermediate_energy_kWh * intermediate_rate_mxn_kwh
  + peak_energy_kWh * peak_rate_mxn_kwh
```

### Demanda facturable

El documento de referencia define:

```text
Ddist = MIN(MAX(...), ...)
Dcap = MIN(...)
```

En este simulador se adapta a la simulacion anual agrupada por meses:

```text
Dlim = monthly_energy_kWh / (hours_in_month * demand_limit_load_factor)

Ddist = min(max(Dbase, Dintermedia, Dpunta), Dlim)

Dcap = min(Dpunta, Dlim)
```

Donde `Dbase`, `Dintermedia` y `Dpunta` son las demandas maximas mensuales dentro de cada periodo.

Sin FV se usa `demand_kW`. Con FV se usa `grid_power_kW`.

```text
distribution_cost = Ddist * distribution_rate_mxn_kw

capacity_cost = Dcap * capacity_rate_mxn_kw

demand_cost = distribution_cost + capacity_cost
```

### Factor de potencia global

El factor de potencia global mensual se calcula como:

```text
fp_global =
sum(active_power) /
sqrt(sum(active_power)^2 + sum(reactive_power)^2)
```

La potencia reactiva se obtiene de:

- `reactive_power_kVAr` si existe;
- `apparent_power_kVA` si existe;
- `power_factor` si existe;
- cero si no hay datos disponibles.

El ajuste por factor de potencia es:

```text
fp_adjustment = (3 / 5) * (0.9 / fp_global - 1)
```

Si `fp_global < 0.90`, el ajuste aumenta el costo. Si `fp_global > 0.90`, lo reduce.

### IVA y total final

```text
subtotal_before_fp = energy_cost + demand_cost

subtotal_after_fp =
    max(0, subtotal_before_fp + subtotal_before_fp * fp_adjustment)
    + fixed_monthly_charge_mxn

iva_mxn = subtotal_after_fp * iva_rate

total_mxn = subtotal_after_fp + iva_mxn
```

El cargo fijo se aplica a los dos escenarios, con y sin FV, por lo que no genera ahorro artificial.

## Diferencia entre el ejemplo GDMTH y este simulador

El archivo `Especificaciones_Tarifario_GDMTH.md` describe un ejemplo economico tipo Excel. Ese ejemplo es util como referencia conceptual, pero no se copio literalmente porque el simulador tiene un modelo fisico anual mas completo.

| Aspecto | Ejemplo GDMTH | Este simulador |
|---|---|---|
| Horizonte | un dia tipico multiplicado por 30 | ano completo con 35,040 intervalos de 15 minutos |
| Separacion tarifaria | manual por posicion de filas | automatica con timestamps reales |
| Generacion FV | seno idealizado | irradiancia, POA, tilt, azimuth, temperatura y pvlib |
| Energia mensual | extrapolacion `dia * 30` | suma real por mes simulado |
| Demanda facturable | formulas mensuales sobre perfil tipico | formulas adaptadas a maximos mensuales reales |
| Factor de potencia | kW/kVAr del perfil | kW/kVAr, kVA o power factor si estan disponibles |
| Uso principal | referencia economica | simulacion tecnico-economica anual |

El ejemplo GDMTH sirve como guia conceptual para energia por periodos, demanda de distribucion, demanda de capacidad, factor de potencia e IVA. Este simulador conserva esas ideas, pero las aplica sobre la serie anual completa, sin degradar el modelo a un dia representativo.

## Supuestos

- La simulacion usa intervalos de 15 minutos durante el ano seleccionado.
- La energia se calcula como potencia media del intervalo por 0.25 h.
- Los horarios GDMTH son aproximados y simplificados.
- La demanda sintetica representa un perfil industrial generico, no una planta especifica.
- Si se carga demanda real incompleta, se interpola o rellena a 15 minutos.
- La potencia reactiva puede estimarse a partir de kVA o factor de potencia si no viene explicitamente.
- Con FV, la potencia reactiva de la carga se conserva salvo que el archivo de entrada indique otra cosa.
- El sistema FV no modela clipping de inversor, degradacion anual, suciedad separada, sombras ni indisponibilidad.
- No se modelan baterias, peak shaving, payback, ROI ni costos de instalacion.

## Limitaciones

- No sustituye facturacion oficial de CFE.
- No incluye calendarios oficiales por region, temporada o contrato.
- No modela compensacion economica por energia exportada.
- No optimiza capacidad FV.
- No calcula retorno de inversion.
- La demanda sintetica es util para escenarios, pero debe reemplazarse por demanda real cuando existan datos medidos.
- La calidad de resultados con irradiancia externa depende de la calidad, cobertura y zona horaria del archivo o proveedor.

## Pruebas realizadas

La suite de pruebas esta en `tests/test_engines.py`. Cubre conversiones de irradiancia, simulacion FV, demanda, balances energeticos y tarifa.

### Estado de validacion

| Modulo | Que se valido | Tests relacionados | Estado |
|---|---|---|---|
| Irradiancia externa | alias de columnas, rechazo de archivos cortos, remuestreo a 15 minutos | `test_standardize_irradiance_table_accepts_common_column_names`, `test_pvgis_horizontal_poa_can_be_resampled_as_ghi`, `test_short_irradiance_file_is_rejected` | Validado |
| Generacion FV | columnas esperadas, potencia nominal como base, perdidas, energia 15 min, no negatividad | `test_pv_simulation_has_expected_columns_when_pvlib_is_available`, `test_pv_generation_uses_nominal_installed_power_when_pvlib_is_available` | Validado |
| Consistencia de panel | advertencia no bloqueante si Wp difiere de area por eficiencia | `test_inconsistent_panel_inputs_create_warning_without_stopping_simulation` | Validado |
| Balance energetico | autoconsumo, exportacion, red, balances por intervalo y anuales | `test_interval_and_annual_energy_balances_are_conserved` | Validado |
| Demanda sintetica | maximo, factor de planta, factor de potencia, fines de semana, verano, semilla reproducible | `test_industrial_demand_profile_uses_inputs_and_preserves_units`, `test_industrial_demand_profile_responds_to_capacity_and_plant_factor`, `test_industrial_demand_profile_has_weekend_and_summer_differentiation`, `test_industrial_demand_profile_is_reproducible_by_seed` | Validado |
| Demanda real | lectura CSV, energia calculada, negativos rechazados, power factor, resolucion 15 min, compatibilidad con simulacion | `test_read_uploaded_demand_accepts_valid_csv_and_calculates_energy`, `test_read_uploaded_demand_rejects_negative_demand`, `test_read_uploaded_demand_uses_file_power_factor_for_apparent_power`, `test_read_uploaded_demand_converts_to_15_min_resolution_and_warns_on_gaps`, `test_real_demand_profile_is_compatible_with_simulation_balance_columns` | Validado |
| Periodos GDMTH | clasificacion Base/Intermedia/Punta y separacion por timestamps reales | `test_gdmth_period_classification_includes_weekend_schedule`, `test_tariff_period_energy_is_separated_from_real_timestamps` | Validado |
| Tarifa GDMTH | costos con/sin FV, cargo fijo, demanda, periodos, IVA, factor de potencia, resumen mensual/anual | `test_tariff_cost_is_lower_with_pv_when_there_is_self_consumption`, `test_tariff_savings_are_zero_without_pv_generation`, `test_fixed_charge_does_not_create_artificial_absolute_savings`, `test_disabling_demand_charge_reduces_total_costs`, `test_higher_energy_rates_increase_energy_costs`, `test_monthly_and_annual_tariff_summaries_are_consistent_and_non_negative`, `test_low_power_factor_increases_tariff_total`, `test_iva_increases_final_tariff_total_without_changing_energy`, `test_distribution_and_capacity_charges_impact_tariff_cost`, `test_billable_demands_change_with_monthly_maximum_demand`, `test_tariff_period_rates_affect_total_cost` | Validado |

## Estado actual

Al cierre de esta documentacion, la suite esperada es:

```text
46 passed
```

Esto indica que el modelo conserva unidades, balances fisicos y consistencia economica basica bajo los supuestos descritos.
