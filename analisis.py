import pandas as pd
import matplotlib.pyplot as plt
import os

def analizar_resultados():
    if not os.path.exists("salida/accidentes.csv") or not os.path.exists("salida/hospitales.csv"):
        print("Faltan los archivos CSV en salida/.")
        return

    # Cargar datos
    df_acc = pd.read_csv("salida/accidentes.csv")
    df_hosp = pd.read_csv("salida/hospitales.csv")
    
    # --- Tarea 5.2: Indicadores ---
    # Filtrar misiones con llegada registrada
    df_llegadas = df_acc[df_acc["t_llegada"] > 0].copy()
    df_llegadas["t_respuesta"] = df_llegadas["t_llegada"] - df_llegadas["t_despacho"]
    
    print("--- RESUMEN ESTADÍSTICO ---")
    print(f"Total de accidentes registrados: {len(df_acc)}")
    if not df_llegadas.empty:
        mediana = df_llegadas["t_respuesta"].median()
        p90 = df_llegadas["t_respuesta"].quantile(0.90)
        print(f"Tiempo de respuesta (Despacho -> Llegada): Mediana = {mediana:.1f} s | P90 = {p90:.1f} s")
        
        retornos_distintos = (df_llegadas["hospital_origen"] != df_llegadas["hospital_retorno"]).sum()
        pct_distintos = (retornos_distintos / len(df_llegadas)) * 100
        print(f"Retornos a hospital distinto al origen: {pct_distintos:.1f}%")
        
    print("\n--- USO POR HOSPITAL ---")
    print(df_hosp[["hospital", "tipo", "stock_ini", "despachos", "retornos", "rechazos", "utilizacion"]].to_string(index=False))

    # --- Tarea 5.3: Gráficos ---
    if not df_llegadas.empty:
        # Gráfico A: Tiempo de respuesta por accidente
        plt.figure(figsize=(10, 5))
        barras = plt.bar(df_llegadas.index.astype(str), df_llegadas["t_respuesta"], color="#002d5a")
        plt.axhline(mediana, color="gray", linestyle="--", label=f"Mediana: {mediana:.0f} s")
        plt.axhline(p90, color="red", linestyle=":", label=f"P90: {p90:.0f} s")
        plt.xlabel("Accidente (Índice)")
        plt.ylabel("Tiempo de respuesta (s)")
        plt.title("Tiempo de respuesta de la ambulancia")
        plt.legend()
        plt.tight_layout()
        plt.savefig("salida/fig_respuesta.png", dpi=150)
        
        # Gráfico B: Uso de ambulancias por hospital
        plt.figure(figsize=(10, 5))
        x = range(len(df_hosp))
        w = 0.25
        plt.bar([i - w for i in x], df_hosp["stock_ini"], width=w, label="Stock inicial", color="#d3d3d3")
        plt.bar(x, df_hosp["despachos"], width=w, label="Despachos", color="#002d5a")
        plt.bar([i + w for i in x], df_hosp["retornos"], width=w, label="Retornos", color="#5c8cbc")
        plt.xticks(x, df_hosp["hospital"], rotation=45)
        plt.ylabel("Ambulancias")
        plt.title("Uso de ambulancias por hospital")
        plt.legend()
        plt.tight_layout()
        plt.savefig("salida/fig_uso.png", dpi=150)
        
        print("\n[Fase 5] Gráficos exportados en salida/fig_respuesta.png y salida/fig_uso.png")

if __name__ == "__main__":
    analizar_resultados()
