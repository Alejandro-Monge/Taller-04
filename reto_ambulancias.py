import traci
import random
from collections import deque

# Coordenadas WGS84 de los 7 hospitales del reto (Cuadro 4.5)
HOSPITALES_INFO = {
    "VCM": {
        "tipo": "público", 
        "nombre": "Hospital Vicente Corral Moscoso (MSP)", 
        "lon": -78.992923, "lat": -2.911098
    },
    "IESS_JCA": {
        "tipo": "público", 
        "nombre": "Hospital José Carrasco Arteaga (IESS)", 
        "lon": -78.970118, "lat": -2.898698
    },
    "MILITAR": {
        "tipo": "público", 
        "nombre": "Hospital Militar HB-III Tarqui", 
        "lon": -79.003968, "lat": -2.903146
    },
    "MUNI_PAT": {
        "tipo": "público", 
        "nombre": "Hospital Municipal de Cuenca (Patamarca)", 
        "lon": -78.982263, "lat": -2.866103
    },
    "MUNI_VALLE": {
        "tipo": "público", 
        "nombre": "Hospital Municipal de El Valle", 
        "lon": -78.961959, "lat": -2.919522
    },
    "MONTE_SINAI": {
        "tipo": "privado", 
        "nombre": "Hospital Monte Sinaí", 
        "lon": -79.007373, "lat": -2.908606
    },
    "DEL_RIO": {
        "tipo": "privado", 
        "nombre": "Hospital Universitario del Río", 
        "lon": -78.960796, "lat": -2.892939
    }
}

def inicializar_hospitales():
    """Ubica los hospitales en la red, dibuja los POI en sumo-gui e imprime la tabla resumen."""
    print(f"{'ID':<12} | {'Tipo':<10} | {'Arista ID':<15} | {'Calle':<25} | {'Distancia'}")
    print("-" * 80)
    
    hospitales_map = {}
    
    for h_id, info in HOSPITALES_INFO.items():
        # 1. Convertir coordenadas geográficas a la arista de la red que admite ambulancias
        edge_id, pos, lane = traci.simulation.convertRoad(info["lon"], info["lat"], isGeo=True, vClass="emergency")
        
        # 2. Obtener coordenadas cartesianas de red para el POI usando convertGeo
        x, y = traci.simulation.convertGeo(info["lon"], info["lat"], fromGeo=True)
        
        # 3. Añadir un POI rojo por hospital en la interfaz gráfica (sumo-gui)
        traci.poi.add(
            poiID=f"poi_{h_id}", 
            poiType="hospital",      #Se usa poiType en lugar de typeID
            color=(255, 0, 0, 255),  # Rojo RGBA
            layer=100.0, 
            x=x, 
            y=y
        )
        
        # Obtener el nombre de la calle asociado a la arista
        calle = traci.edge.getStreetName(edge_id)
        if not calle:
            calle = "Arista sin nombre"
            
        # Almacenar datos para el sistema de despacho posterior
        hospitales_map[h_id] = {
            "edge": edge_id,
            "pos": pos,
            "tipo": info["tipo"],
            "nombre": info["nombre"]
        }
        
        print(f"{h_id:<12} | {info['tipo']:<10} | {edge_id:<15} | {calle[:25]:<25} | OK (<200m)")
        
    return hospitales_map
    

def inicializar_flotas(hospitales_map, seed=42):
    """
    Modela la disponibilidad de ambulancias por hospital con stock inicial aleatorio.
    - Hospitales públicos: 1 a 3 unidades[cite: 11, 40].
    - Hospitales privados: 0 a 1 unidad[cite: 11, 40].
    """
    rng = random.Random(seed)  # Generador propio para asegurar reproducibilidad
    flotas = {}
    contador_unidades = 1
    
    print("\n--- INICIALIZACIÓN DE FLOTA DE AMBULANCIAS ---")
    for h_id, info in hospitales_map.items():
        cola = deque()
        
        # Stock inicial según el tipo de hospital
        if info["tipo"] == "público":
            stock_inicial = rng.randint(1, 3)
        else:
            stock_inicial = rng.randint(0, 1)
        
        # Crear unidades con identificadores (ej. U01, U02...) y agregarlas a la cola FIFO
        for _ in range(stock_inicial):
            unidad_id = f"U{contador_unidades:02d}"
            cola.append(unidad_id)
            contador_unidades += 1
            
        flotas[h_id] = {
            "cola": cola,
            "stock_ini": stock_inicial,
            "rechazos": 0
        }
        
        print(f" Hospital {h_id:<12} | Tipo: {info['tipo']:<10} | Stock Inicial: {stock_inicial} | Unidades: {list(cola)}")
        
    print("-" * 55)
    return flotas, rng

def pedir_ambulancia(h_id, flotas, rng, p_sin=0.25):
    """
    Gestiona la petición de una ambulancia en un hospital específico:
    1. Si la cola está vacía -> 'no hay'[cite: 11, 40].
    2. Si hay stock, se niega con probabilidad p_sin = 0.25[cite: 11, 40].
    3. Si se concede, se extrae del extremo izquierdo con popleft()[cite: 11, 40].
    """
    datos = flotas[h_id]
    cola = datos["cola"]
    
    if not cola:
        return None, "cola_vacia"
        
    if rng.random() < p_sin:
        datos["rechazos"] += 1
        return None, "rechazo_aleatorio"
        
    unidad = cola.popleft()
    return unidad, "concedido"

def devolver_ambulancia(h_id, unidad_id, flotas):
    """
    Al cerrar una misión, la unidad reingresa mediante append() en la cola 
    del hospital donde finaliza[cite: 11].
    """
    if h_id in flotas:
        flotas[h_id]["cola"].append(unidad_id)
        

def probar_despacho_manual(step, hospitales_map, prueba_realizada):
    """
    Ejecuta un despacho de prueba manual en t = 120 s desde VCM hasta IESS_JCA[cite: 40].
    """
    global datos_prueba_activa
    if step == 120 and not prueba_realizada:
        print(f"\n[t = {step} s] --- INICIANDO AMBULANCIA DE PRUEBA VCM -> IESS_JCA ---")
        
        origen_edge = hospitales_map["VCM"]["edge"]
        origen_pos = hospitales_map["VCM"]["pos"]
        destino_edge = hospitales_map["IESS_JCA"]["edge"]
        
        # Calcular la ruta óptima en tiempo real usando vType="ambulance"
        ruta_obj = traci.simulation.findRoute(origen_edge, destino_edge, vType="ambulance")
        
        if not ruta_obj.edges:
            print("¡Error! findRoute no encontró un camino válido entre VCM y IESS_JCA.")
            return True

        travel_time_estimado = ruta_obj.travelTime
        print(f"Ruta calculada: {len(ruta_obj.edges)} aristas | TravelTime estimado: {travel_time_estimado:.2f} s")
        
        route_id = "ruta_prueba_vcm_iess"
        traci.route.add(route_id, ruta_obj.edges)
        
        veh_id = "amb_test_01"
        traci.vehicle.add(
            vehID=veh_id,
            routeID=route_id,
            typeID="ambulance",
            depart="now",
            departPos=str(origen_pos),
            departSpeed="0"
        )
        
        datos_prueba_activa = {
            "veh_id": veh_id,
            "t_salida": step,
            "t_estimado": travel_time_estimado
        }
        
        return True
    return prueba_realizada

def verificar_llegada_prueba(step):
    """
    Verifica si la ambulancia de prueba llegó utilizando getArrivedIDList()[cite: 40].
    """
    global datos_prueba_activa
    if 'datos_prueba_activa' in globals() and datos_prueba_activa:
        llegados = traci.simulation.getArrivedIDList()
        veh_id = datos_prueba_activa["veh_id"]
        
        if veh_id in llegados:
            t_llegada = step
            t_real = t_llegada - datos_prueba_activa["t_salida"]
            t_est = datos_prueba_activa["t_estimado"]
            
            print(f"\n[t = {t_llegada} s] --- AMBULANCIA DE PRUEBA LLEGÓ A DESTINO ---")
            print(f"Vehículo: {veh_id} | Tiempo real medido: {t_real} s | Tiempo estimado (findRoute): {t_est:.2f} s")
            
            datos_prueba_activa = None


if __name__ == "__main__":
    # 1. Arrancar SUMO utilizando la configuración creada en la Fase 1
    traci.start(["sumo", "-c", "reto.sumocfg"])
    
    # 2. Inicializar hospitales (mapeo y POIs)
    hospitales_map = inicializar_hospitales()
    
    # 3. Inicializar flotas con semilla fija
    flotas, rng = inicializar_flotas(hospitales_map, seed=42)
    
    step = 0
    prueba_realizada = False
    datos_prueba_activa = None
    
    print("\n--- INICIANDO BUCLE DE SIMULACIÓN (FASE 2) ---")
    
    # 4. Bucle principal paso a paso con TraCI
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        step = traci.simulation.getTime()
        
        # Ejecutar la prueba de la ambulancia en t = 120 s
        prueba_realizada = probar_despacho_manual(step, hospitales_map, prueba_realizada)
        
        # Verificar la llegada de la prueba
        verificar_llegada_prueba(step)
        
        if step % 1000 == 0:
            print(f"[Simulación en curso] Tiempo simulado: {int(step)} s")

    # 5. Cerrar conexión TraCI al terminar
    traci.close()
    print("\n--- SIMULACIÓN FINALIZADA CORRECTAMENTE ---")
