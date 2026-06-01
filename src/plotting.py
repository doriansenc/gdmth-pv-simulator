from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from src.ui_components import PALETTE


MONTH_ORDER = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _ordered_monthly_energy(df: pd.DataFrame) -> pd.DataFrame:
    monthly = df.groupby(["month", "month_name"], as_index=False).agg(
        generation_kWh=("energy_kWh", "sum"),
        demand_kWh=("demand_energy_kWh", "sum"),
        self_consumed_kWh=("self_consumed_kWh", "sum"),
        grid_energy_kWh=("grid_energy_kWh", "sum"),
        exported_kWh=("exported_kWh", "sum"),
    )
    monthly["month_name"] = pd.Categorical(monthly["month_name"], categories=MONTH_ORDER, ordered=True)
    return monthly.sort_values("month")


def _base_layout(fig: go.Figure, height: int = 420) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin=dict(l=30, r=20, t=60, b=35),
        font=dict(family="Arial", size=13, color=PALETTE["gray_text"]),
        title_font=dict(size=18, color=PALETTE["navy"]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=True, gridcolor="#EEF2F6")
    fig.update_yaxes(showgrid=True, gridcolor="#EEF2F6")
    return fig


def plot_daily_irradiance(df_day: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df_day["datetime"],
            y=df_day["GHI_W_m2"],
            mode="lines",
            name="GHI",
            line=dict(color=PALETTE["navy"], width=2.4),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df_day["datetime"],
            y=df_day["POA_W_m2"],
            mode="lines",
            name="POA",
            line=dict(color=PALETTE["solar"], width=3),
        )
    )
    fig.update_layout(
        title="Irradiancia horizontal y en plano del arreglo",
        xaxis_title="Hora",
        yaxis_title="Irradiancia [W/m²]",
    )
    return _base_layout(fig)


def plot_poa_components(df_day: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df_day["datetime"],
            y=df_day["POA_beam_W_m2"],
            mode="lines",
            name="Componente directa",
            line=dict(color=PALETTE["solar_dark"], width=2.3),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df_day["datetime"],
            y=df_day["POA_diffuse_W_m2"],
            mode="lines",
            name="Componente difusa",
            line=dict(color=PALETTE["navy_2"], width=2.3),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df_day["datetime"],
            y=df_day["POA_ground_W_m2"],
            mode="lines",
            name="Reflexión del suelo",
            line=dict(color=PALETTE["green"], width=2.3),
        )
    )
    fig.update_layout(
        title="Componentes de irradiancia POA",
        xaxis_title="Hora",
        yaxis_title="Irradiancia [W/m²]",
    )
    return _base_layout(fig)


def plot_daily_generation_vs_demand(df_day: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df_day["datetime"],
            y=df_day["generation_kW"],
            mode="lines",
            name="Generación PV",
            line=dict(color=PALETTE["green"], width=3),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df_day["datetime"],
            y=df_day["demand_kW"],
            mode="lines",
            name="Demanda",
            line=dict(color=PALETTE["navy"], width=3),
        )
    )
    fig.update_layout(
        title="Generación fotovoltaica contra demanda",
        xaxis_title="Hora",
        yaxis_title="Potencia [kW]",
    )
    return _base_layout(fig)


def plot_monthly_energy(df: pd.DataFrame) -> go.Figure:
    monthly = _ordered_monthly_energy(df)

    fig = go.Figure()
    traces = [
        ("Generación FV", "generation_kWh", PALETTE["solar"]),
        ("Demanda", "demand_kWh", PALETTE["navy"]),
        ("Autoconsumo", "self_consumed_kWh", PALETTE["green"]),
        ("Energía de red", "grid_energy_kWh", PALETTE["navy_2"]),
        ("Exportación", "exported_kWh", PALETTE["solar_dark"]),
    ]
    for name, column, color in traces:
        fig.add_trace(
            go.Bar(
                x=monthly["month_name"],
                y=monthly[column],
                name=name,
                marker_color=color,
            )
        )
    fig.update_layout(
        title="Energía mensual: generación, demanda y flujos",
        xaxis_title="Mes",
        yaxis_title="Energía [kWh]",
        barmode="group",
    )
    return _base_layout(fig)


def plot_monthly_energy_balance(df: pd.DataFrame) -> go.Figure:
    monthly = _ordered_monthly_energy(df)

    fig = go.Figure()
    for name, column, color in [
        ("Autoconsumo", "self_consumed_kWh", PALETTE["green"]),
        ("Energía de red", "grid_energy_kWh", PALETTE["navy"]),
        ("Exportación", "exported_kWh", PALETTE["solar"]),
    ]:
        fig.add_trace(
            go.Bar(
                x=monthly["month_name"],
                y=monthly[column],
                name=name,
                marker_color=color,
            )
        )
    fig.update_layout(
        title="Balance energético mensual",
        xaxis_title="Mes",
        yaxis_title="Energía [kWh]",
        barmode="group",
    )
    return _base_layout(fig)


def plot_hourly_average(df: pd.DataFrame) -> go.Figure:
    hourly = df.groupby("hour", as_index=False).agg(
        generation_kW=("generation_kW", "mean"),
        demand_kW=("demand_kW", "mean"),
        poa=("POA_W_m2", "mean"),
    )

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=hourly["hour"],
            y=hourly["generation_kW"],
            mode="lines+markers",
            name="Generación promedio",
            line=dict(color=PALETTE["green"], width=3),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=hourly["hour"],
            y=hourly["demand_kW"],
            mode="lines+markers",
            name="Demanda promedio",
            line=dict(color=PALETTE["navy"], width=3),
        )
    )
    fig.update_layout(
        title="Perfil horario promedio anual",
        xaxis_title="Hora del día",
        yaxis_title="Potencia promedio [kW]",
    )
    return _base_layout(fig)


def plot_net_energy_flow(df: pd.DataFrame) -> go.Figure:
    totals = pd.DataFrame(
        {
            "Flujo energético": ["Autoconsumo", "Exportación", "Energía de red"],
            "Energía [kWh]": [
                df["self_consumed_kWh"].sum(),
                df["exported_kWh"].sum(),
                df["grid_energy_kWh"].sum(),
            ],
        }
    )
    fig = px.bar(
        totals,
        x="Flujo energético",
        y="Energía [kWh]",
        text_auto=".0f",
        color="Flujo energético",
        color_discrete_map={
            "Autoconsumo": PALETTE["green"],
            "Exportación": PALETTE["solar"],
            "Energía de red": PALETTE["navy"],
        },
        title="Balance energético anual",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Energía [kWh]")
    return _base_layout(fig)


def plot_monthly_tariff_savings(monthly: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=monthly["month"],
            y=monthly["total_without_pv_mxn"],
            name="Sin sistema PV",
            marker_color=PALETTE["navy"],
        )
    )
    fig.add_trace(
        go.Bar(
            x=monthly["month"],
            y=monthly["total_with_pv_mxn"],
            name="Con sistema PV",
            marker_color=PALETTE["green"],
        )
    )
    fig.add_trace(
        go.Scatter(
            x=monthly["month"],
            y=monthly["estimated_savings_mxn"],
            mode="lines+markers",
            name="Ahorro mensual",
            line=dict(color=PALETTE["solar_dark"], width=3),
            marker=dict(size=8),
        )
    )
    fig.update_layout(
        title="Costo eléctrico mensual y ahorro FV",
        xaxis_title="Mes",
        yaxis_title="Costo estimado [MXN]",
        barmode="group",
    )
    return _base_layout(fig)


def plot_tariff_energy_by_period(monthly: pd.DataFrame) -> go.Figure:
    periods = [
        ("Base", "base_energy_without_pv_kWh", "base_energy_with_pv_kWh"),
        ("Intermedia", "intermediate_energy_without_pv_kWh", "intermediate_energy_with_pv_kWh"),
        ("Punta", "peak_energy_without_pv_kWh", "peak_energy_with_pv_kWh"),
    ]
    rows = []
    for period, without_col, with_col in periods:
        if without_col in monthly.columns:
            rows.append({"Periodo": period, "Escenario": "Sin FV", "Energía [kWh]": float(monthly[without_col].sum())})
        if with_col in monthly.columns:
            rows.append({"Periodo": period, "Escenario": "Con FV", "Energía [kWh]": float(monthly[with_col].sum())})

    data = pd.DataFrame(rows)
    fig = px.bar(
        data,
        x="Periodo",
        y="Energía [kWh]",
        color="Escenario",
        barmode="group",
        text_auto=".0f",
        color_discrete_map={"Sin FV": PALETTE["navy"], "Con FV": PALETTE["green"]},
        title="Energía anual por periodo tarifario GDMTH",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(xaxis_title="Periodo", yaxis_title="Energía [kWh]")
    return _base_layout(fig)


def plot_tariff_component_breakdown(monthly: pd.DataFrame) -> go.Figure:
    components = [
        ("Energía", "energy_cost_without_pv_mxn", "energy_cost_with_pv_mxn"),
        ("Distribución", "distribution_cost_without_pv_mxn", "distribution_cost_with_pv_mxn"),
        ("Capacidad", "capacity_cost_without_pv_mxn", "capacity_cost_with_pv_mxn"),
        ("Ajuste FP", "power_factor_adjustment_without_pv_mxn", "power_factor_adjustment_with_pv_mxn"),
        ("Cargo fijo", "fixed_charge_mxn", "fixed_charge_mxn"),
        ("IVA", "iva_without_pv_mxn", "iva_with_pv_mxn"),
    ]
    rows = []
    for component, without_col, with_col in components:
        if without_col in monthly.columns:
            rows.append({"Componente": component, "Escenario": "Sin FV", "Costo [MXN]": float(monthly[without_col].sum())})
        if with_col in monthly.columns:
            rows.append({"Componente": component, "Escenario": "Con FV", "Costo [MXN]": float(monthly[with_col].sum())})

    data = pd.DataFrame(rows)
    fig = px.bar(
        data,
        x="Componente",
        y="Costo [MXN]",
        color="Escenario",
        barmode="group",
        text_auto=".0f",
        color_discrete_map={"Sin FV": PALETTE["navy"], "Con FV": PALETTE["green"]},
        title="Desglose anual de componentes tarifarios",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(xaxis_title="", yaxis_title="Costo estimado [MXN]")
    return _base_layout(fig)


def plot_scenario_generation(scenarios: pd.DataFrame) -> go.Figure:
    fig = px.scatter(
        scenarios,
        x="installed_power_kw",
        y="annual_generation_kWh",
        size="coverage_percent",
        color="tilt_deg",
        hover_data=["scenario", "number_of_panels", "azimuth_deg", "specific_yield_kWh_kWp"],
        title="Comparación de escenarios: potencia instalada contra generación anual",
        labels={
            "installed_power_kw": "Potencia instalada [kW]",
            "annual_generation_kWh": "Generación anual [kWh]",
            "tilt_deg": "Tilt [°]",
        },
        color_continuous_scale="Viridis",
    )
    return _base_layout(fig)


def plot_scenario_coverage(scenarios: pd.DataFrame) -> go.Figure:
    fig = px.bar(
        scenarios.sort_values("coverage_percent", ascending=False),
        x="scenario",
        y="coverage_percent",
        color="number_of_panels",
        title="Cobertura de demanda por escenario",
        labels={"coverage_percent": "Cobertura [%]", "scenario": "Escenario"},
        color_continuous_scale="Teal",
    )
    return _base_layout(fig)
