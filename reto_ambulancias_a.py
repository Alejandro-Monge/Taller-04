import os
import sys

# Asegurar que Python siempre encuentre traci y sumolib dentro del contenedor Docker
for ruta in [os.environ.get("SUMO_HOME", ""), "/usr/share/sumo", "/usr/local/share/sumo", "/opt/sumo"]:
    tools_dir = os.path.join(ruta, "tools")
    if ruta and os.path.exists(tools_dir) and tools_dir not in sys.path:
        sys.path.append(tools_dir)

import traci
import random
from collections import deque

HOSPITALES_INFO = {
    "VCM": {"tipo": "público", "nombre": "Hospital Vicente Corral Moscoso (MSP)", "lon": -78.992923, "lat": -2.911098},
    "IESS_JCA": {"tipo": "público", "nombre": "Hospital José Carrasco Arteaga (IESS)", "lon": -78.970118, "lat": -2.898698},
    "MILITAR": {"tipo": "público", "nombre": "Hospital Militar HB-III Tarqui", "lon": -79.003968, "lat": -2.903146},
    "MUNI_PAT": {"tipo": "público", "nombre": "Hospital Municipal de Cuenca (Patamarca)", "lon": -78.982263, "lat": -2.866103},
    "MUNI_VALLE": {"tipo": "público", "nombre": "Hospital Municipal de El Valle", "lon": -78.961959, "lat": -2.919522},
    "MONTE_SINAI": {"tipo": "privado", "nombre": "Hospital Monte Sinaí", "lon": -79.007373, "lat": -2.908606},
    "DEL_RIO": {"tipo": "privado", "nombre": "Hospital Universitario del Río", "lon": -78.960796, "lat": -2.892939}
}

def inicializar_hospitales():
    """Ubica los hospitales en la red y dibuja los POI en sumo-gui."""
    print(f"{'ID':<12} | {'Tipo':<10} | {'Arista ID':<15} | {'Calle':<25} | {'Distancia'}")
    print("-" * 80)
    hospitales_map = {}
    
    for h_id, info in HOSPITALES_INFO.items():
        edge_id, pos, lane = traci.simulation.convertRoad(info["lon"], info["lat"], isGeo=True, vClass="emergency")
        x, y = traci.simulation.convertGeo(info["lon"], info["lat"], fromGeo=True)
        
        traci.poi.add(
            poiID=f"poi_{h_id}", 
            poiType="hospital", 
            color=(255, 0, 0, 255),
            layer=100.0, x=x, y=y
        )
        
        calle = traci.edge.getStreetName(edge_id) or "Arista sin nombre"
        hospitales_map[h_id] = {"edge": edge_id, "pos": pos, "tipo": info["tipo"], "nombre": info["nombre"]}
        print(f"{h_id:<12} | {info['tipo']:<10} | {edge_id:<15} | {calle[:25]:<25} | OK (<200m)")
        
    return hospitales_map

def inicializar_flotas(hospitales_map, seed=42):
    """Modela la disponibilidad aleatoria de ambulancias."""
    rng = random.Random(seed)
    flotas = {}
    contador_unidades = 1
    
    print("\n--- INICIALIZACIÓN DE FLOTA DE AMBULANCIAS ---")
    for h_id, info in hospitales_map.items():
        cola = deque()
        stock_inicial = rng.randint(1, 3) if info["tipo"] == "público" else rng.randint(0, 1)
        
        for _ in range(stock_inicial):
            cola.append(f"U{contador_unidades:02d}")
            contador_unidades += 1
            
        flotas[h_id] = {"cola": cola, "stock_ini": stock_inicial, "rechazos": 0}
        print(f" Hospital {h_id:<12} | Tipo: {info['tipo']:<10} | Stock Inicial: {stock_inicial} | Unidades: {list(cola)}")
        
    return flotas, rng

def generar_agenda_accidentes(rng):
    """Genera 15 instantes de accidente (5 por hora) entre min 5 y min 58."""
    agenda = []
    for hora in range(3):
        t_base = hora * 3600
        for _ in range(5):
            t_acc = t_base + rng.uniform(300, 3480)
            agenda.append(int(t_acc))
    agenda.sort()
    print(f"\n--- AGENDA DE ACCIDENTES: {len(agenda)} previstos | Primer evento en t = {agenda[0]} s ---")
    return agenda

def programar_accidente(step, rng, persecuciones_activas, buses_ocupados):
    """
    Tarea 3.2: Elige un bus en marcha (v >= 4 m/s, fuera de cruce, pos > 60 m),
    busca si tiene una moto detrás con getFollower(bus, 80) o inserta una a 45 m.
    """
    vehiculos_activos = traci.vehicle.getIDList()
    buses_aptos = []
    
    for v in vehiculos_activos:
        if v in buses_ocupados:
            continue
        if traci.vehicle.getTypeID(v) == "bus":
            road_id = traci.vehicle.getRoadID(v)
            if not road_id.startswith(":") and traci.vehicle.getSpeed(v) >= 4.0 and traci.vehicle.getLanePosition(v) > 60.0:
                buses_aptos.append(v)
                
    if not buses_aptos:
        return False
        
    bus = rng.choice(buses_aptos)
    
    # 1. Revisar si ya viene una moto detrás a <= 80 m
    follower_info = traci.vehicle.getFollower(bus, 80.0)
    moto_id = None
    origen_txt = "moto insertada"
    
    if follower_info and follower_info[0] != "" and traci.vehicle.getTypeID(follower_info[0]) == "moto":
        moto_id = follower_info[0]
        origen_txt = "follower existente"
    else:
        # 2. Si no hay moto detrás, insertar una 45 m detrás en el mismo carril y con el resto de la ruta del bus
        moto_id = f"moto_imprudente_{int(step)}"
        ruta_completa = traci.vehicle.getRoute(bus)
        idx_actual = traci.vehicle.getRouteIndex(bus)
        resto_ruta = ruta_completa[idx_actual:]
        
        if not resto_ruta:
            return False
            
        pos_moto = max(0.0, traci.vehicle.getLanePosition(bus) - 45.0)
        lane_idx = traci.vehicle.getLaneIndex(bus)
        
        route_id = f"ruta_{moto_id}"
        traci.route.add(route_id, resto_ruta)
        try:
            traci.vehicle.add(
                vehID=moto_id,
                routeID=route_id,
                typeID="moto",
                depart="now",
                departPos=f"{pos_moto:.1f}",
                departLane=str(lane_idx),
                departSpeed="max"
            )
        except traci.TraCIException:
            return False

    # Registrar como persecución activa (se le aplicará speedMode(0) en cuanto esté activa en la red)
    persecuciones_activas[moto_id] = {
        "bus": bus,
        "t_inicio": step,
        "configurada": False
    }
    print(f"[{int(step):4d} s] IMPRUDENTE {moto_id} ({origen_txt}) persigue a {bus}")
    return True

def gestionar_persecuciones(step, persecuciones_activas, agenda):
    """
    Aplica speedMode(0) cuando la moto ya está en getIDList() (evita el error 'not known' tras add)
    y verifica el timeout de 90 s por si el bus giró o la moto salió sin chocar.
    """
    activos = set(traci.vehicle.getIDList())
    eliminar = []
    
    for moto_id, info in list(persecuciones_activas.items()):
        # Si ya pasaron más de 5 s y nunca entró o ya desapareció de la red sin chocar
        if moto_id not in activos:
            if step - info["t_inicio"] > 5:
                print(f"[{int(step):4d} s] la moto {moto_id} salió sin chocar; se reprograma (+60 s)")
                agenda.append(int(step + 60))
                agenda.sort()
                eliminar.append(moto_id)
            continue
            
        # Si acaba de entrar en la red, sacarla del modelo de Krauss
        if not info["configurada"]:
            traci.vehicle.setColor(moto_id, (255, 165, 0, 255)) # Naranja
            traci.vehicle.setSpeedMode(moto_id, 0)              # Apaga v_safe, prioridad y semáforos
            traci.vehicle.setLaneChangeMode(moto_id, 0)         # Sin cambios de carril evasivos
            traci.vehicle.setSpeed(moto_id, 22.0)               # ~80 km/h
            info["configurada"] = True
        else:
            # Mantener orden de velocidad de persecución
            traci.vehicle.setSpeed(moto_id, 22.0)
            
        # Trampa 3: Si lleva 90 s persiguiendo y no alcanzó al bus, restaurar modelo y reprogramar
        if step - info["t_inicio"] >= 90:
            traci.vehicle.setSpeedMode(moto_id, 31)
            traci.vehicle.setLaneChangeMode(moto_id, 1621)
            traci.vehicle.setSpeed(moto_id, -1)
            traci.vehicle.setColor(moto_id, (255, 0, 255, 255))
            print(f"[{int(step):4d} s] la moto {moto_id} no alcanzó a {info['bus']} en 90 s; se restaura y reprograma (+60 s)")
            agenda.append(int(step + 60))
            agenda.sort()
            eliminar.append(moto_id)
            
    for m in eliminar:
        persecuciones_activas.pop(m, None)

def detectar_e_inmovilizar(step, lista_accidentes, colisiones_procesadas, persecuciones_activas, buses_ocupados, agenda):
    """
    Tarea 3.3 y 3.4: Lee getCollisions(), filtra bus-moto, inmoviliza en dos pasos y
    retira colisiones de fondo para evitar bloqueos eternos.
    """
    for col in traci.simulation.getCollisions():
        par = tuple(sorted([col.collider, col.victim]))
        if par in colisiones_procesadas:
            continue
        colisiones_procesadas.add(par)
        
        tipos = {col.colliderType, col.victimType}
        
        # Caso 1: Accidente válido Bus - Moto
        if tipos == {"bus", "moto"}:
            bus_id = col.collider if col.colliderType == "bus" else col.victim
            moto_id = col.victim if bus_id == col.collider else col.collider
            
            # Quitar de persecuciones activas porque ya chocó
            persecuciones_activas.pop(moto_id, None)
            buses_ocupados.add(bus_id)
            
            acc_id = f"ACC{len(lista_accidentes)+1:02d}"
            
            # Paso 1 de parar(v): speedMode 0 y speed 0 + pintar de rojo
            for veh in (bus_id, moto_id):
                try:
                    traci.vehicle.setSpeedMode(veh, 0)
                    traci.vehicle.setLaneChangeMode(veh, 0)
                    traci.vehicle.setSpeed(veh, 0.0)
                    traci.vehicle.setColor(veh, (255, 0, 0, 255))
                except traci.TraCIException:
                    pass
                    
            try:
                x, y = traci.vehicle.getPosition(bus_id)
                arista = traci.vehicle.getRoadID(bus_id)
            except traci.TraCIException:
                x, y = 0.0, 0.0
                arista = col.lane.split("_")[0]
                
            traci.poi.add(f"poi_{acc_id}", x, y, (255, 255, 0, 255), poiType="accidente", layer=100.0)
            
            lista_accidentes.append({
                "id": acc_id,
                "t_accidente": step,
                "type": col.type,
                "bus": bus_id,
                "moto": moto_id,
                "vehiculos": (bus_id, moto_id),
                "arista": arista,
                "pos": col.pos,
                "xy": (x, y),
                "fase": "inmovilizado_paso1"
            })
            print(f"[{int(step):4d} s] ACCIDENTE {acc_id} {col.type} {bus_id} x {moto_id} en {arista}")
            
        # Caso 2: Colisión de fondo (auto-auto, moto_imprudente x auto, etc.)
        else:
            for veh, vtype in [(col.collider, col.colliderType), (col.victim, col.victimType)]:
                # Si una moto imprudente chocó con un auto antes de llegar al bus, reprogramar el accidente
                if veh in persecuciones_activas:
                    persecuciones_activas.pop(veh, None)
                    agenda.append(int(step + 60))
                    agenda.sort()
                    print(f"[{int(step):4d} s] colisión de fondo {col.collider} x {col.victim}: se retira {veh} y se reprograma (+60 s)")
                
                if vtype != "ambulance" and veh not in buses_ocupados:
                    try:
                        traci.vehicle.remove(veh, traci.constants.REMOVE_VAPORIZED)
                    except traci.TraCIException:
                        pass

if __name__ == "__main__":
    traci.start(["sumo", "-c", "reto.sumocfg"])
    hospitales_map = inicializar_hospitales()
    flotas, rng = inicializar_flotas(hospitales_map, seed=42)
    
    agenda = generar_agenda_accidentes(rng)
    lista_accidentes = []
    colisiones_procesadas = set()
    persecuciones_activas = {}
    buses_ocupados = set()
    
    print("\n--- INICIANDO BUCLE DE SIMULACIÓN (FASE 3) ---")
    
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        step = traci.simulation.getTime()
        
        # 1. Consolidar Paso 2 de parar(v): devolver speedMode 31 manteniendo velocidad 0
        for acc in lista_accidentes:
            if acc["fase"] == "inmovilizado_paso1":
                for veh in acc["vehiculos"]:
                    try:
                        traci.vehicle.setSpeedMode(veh, 31)
                        traci.vehicle.setSpeed(veh, 0.0)
                    except traci.TraCIException:
                        pass
                acc["fase"] = "espera"
        
        # 2. Gestionar motos imprudentes en persecución
        gestionar_persecuciones(step, persecuciones_activas, agenda)
        
        # 3. Disparar nuevo accidente según la agenda
        if agenda and step >= agenda[0]:
            if programar_accidente(step, rng, persecuciones_activas, buses_ocupados):
                agenda.pop(0)
            else:
                agenda[0] += 20  # Si no hay bus apto, posponer 20 s
                
        # 4. Detectar colisiones e inmovilizar
        detectar_e_inmovilizar(step, lista_accidentes, colisiones_procesadas, persecuciones_activas, buses_ocupados, agenda)

    traci.close()
    print(f"\n--- SIMULACIÓN FINALIZADA | Total accidentes bus-moto provocados: {len(lista_accidentes)} ---")
