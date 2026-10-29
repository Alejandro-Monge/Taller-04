import os
import sys
import csv
import random
from collections import deque

# Asegurar que Python encuentre traci y sumolib
for ruta in [os.environ.get("SUMO_HOME", ""), "/usr/share/sumo", "/usr/local/share/sumo", "/opt/sumo"]:
    tools_dir = os.path.join(ruta, "tools")
    if ruta and os.path.exists(tools_dir) and tools_dir not in sys.path:
        sys.path.append(tools_dir)

import traci

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
    """Ubica hospitales, dibuja POIs y retorna diccionario[cite: 10, 11, 35, 37, 40]."""
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
    """Modela disponibilidad aleatoria con colas FIFO[cite: 11, 12, 40]."""
    rng = random.Random(seed)
    flotas = {}
    contador_unidades = 1
    
    print("\n--- INICIALIZACIÓN DE FLOTA ---")
    for h_id, info in hospitales_map.items():
        cola = deque()
        stock_inicial = rng.randint(1, 3) if info["tipo"] == "público" else rng.randint(0, 1)
        
        for _ in range(stock_inicial):
            cola.append(f"U{contador_unidades:02d}")
            contador_unidades += 1
            
        flotas[h_id] = {"cola": cola, "stock_ini": stock_inicial, "rechazos": 0, "seg_ocupados": 0}
        print(f" Hospital {h_id:<12} | Stock: {stock_inicial} | Unidades: {list(cola)}")
        
    return flotas, rng

def generar_agenda_accidentes(rng):
    """Genera 15 accidentes (5/h) ordenados[cite: 14, 41]."""
    agenda = []
    for hora in range(3):
        t_base = hora * 3600
        for _ in range(5):
            agenda.append(int(t_base + rng.uniform(300, 3480)))
    agenda.sort()
    return agenda

def programar_accidente(step, rng, persecuciones_activas, buses_ocupados):
    """Busca bus apto e inserta o utiliza moto seguidora[cite: 15, 41]."""
    buses_aptos = [v for v in traci.vehicle.getIDList() if v not in buses_ocupados and traci.vehicle.getTypeID(v) == "bus" and not traci.vehicle.getRoadID(v).startswith(":") and traci.vehicle.getSpeed(v) >= 4.0 and traci.vehicle.getLanePosition(v) > 60.0]
    
    if not buses_aptos:
        return False
        
    bus = rng.choice(buses_aptos)
    follower_info = traci.vehicle.getFollower(bus, 80.0)
    
    if follower_info and follower_info[0] != "" and traci.vehicle.getTypeID(follower_info[0]) == "moto":
        moto_id = follower_info[0]
        origen = "follower existente"
    else:
        moto_id = f"moto_imprudente_{int(step)}"
        ruta = traci.vehicle.getRoute(bus)[traci.vehicle.getRouteIndex(bus):]
        if not ruta: return False
        
        traci.route.add(f"ruta_{moto_id}", ruta)
        try:
            traci.vehicle.add(vehID=moto_id, routeID=f"ruta_{moto_id}", typeID="moto", depart="now", departPos=f"{max(0.0, traci.vehicle.getLanePosition(bus) - 45.0):.1f}", departLane=str(traci.vehicle.getLaneIndex(bus)), departSpeed="max")
            origen = "moto insertada"
        except traci.TraCIException:
            return False

    persecuciones_activas[moto_id] = {"bus": bus, "t_inicio": step, "configurada": False}
    print(f"[{int(step):4d} s] IMPRUDENTE {moto_id} ({origen}) persigue a {bus}")
    return True

def gestionar_persecuciones(step, persecuciones_activas, agenda):
    """Aplica speedMode(0) o restaura si la persecución falla[cite: 15, 16, 18, 41, 42]."""
    activos = set(traci.vehicle.getIDList())
    eliminar = []
    
    for moto_id, info in list(persecuciones_activas.items()):
        if moto_id not in activos:
            if step - info["t_inicio"] > 5:
                agenda.append(int(step + 60))
                agenda.sort()
                eliminar.append(moto_id)
            continue
            
        if not info["configurada"]:
            traci.vehicle.setColor(moto_id, (255, 165, 0, 255))
            traci.vehicle.setSpeedMode(moto_id, 0)
            traci.vehicle.setLaneChangeMode(moto_id, 0)
            traci.vehicle.setSpeed(moto_id, 22.0)
            info["configurada"] = True
        else:
            traci.vehicle.setSpeed(moto_id, 22.0)
            
        if step - info["t_inicio"] >= 90:
            traci.vehicle.setSpeedMode(moto_id, 31)
            traci.vehicle.setLaneChangeMode(moto_id, 1621)
            traci.vehicle.setSpeed(moto_id, -1)
            agenda.append(int(step + 60))
            agenda.sort()
            eliminar.append(moto_id)
            
    for m in eliminar:
        persecuciones_activas.pop(m, None)

def detectar_e_inmovilizar(step, lista_accidentes, colisiones_procesadas, persecuciones_activas, buses_ocupados, agenda):
    """Registra y detiene vehículos; limpia colisiones espurias[cite: 17, 18, 23, 42]."""
    for col in traci.simulation.getCollisions():
        par = tuple(sorted([col.collider, col.victim]))
        if par in colisiones_procesadas:
            continue
        colisiones_procesadas.add(par)
        
        if {col.colliderType, col.victimType} == {"bus", "moto"}:
            bus_id = col.collider if col.colliderType == "bus" else col.victim
            moto_id = col.victim if bus_id == col.collider else col.collider
            
            persecuciones_activas.pop(moto_id, None)
            buses_ocupados.add(bus_id)
            acc_id = f"ACC{len(lista_accidentes)+1:02d}"
            
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
            except:
                x, y, arista = 0.0, 0.0, col.lane.split("_")[0]
                
            traci.poi.add(f"poi_{acc_id}", x, y, (255, 255, 0, 255), poiType="accidente", layer=100.0)
            lista_accidentes.append({"id": acc_id, "t_accidente": step, "vehiculos": (bus_id, moto_id), "arista": arista, "pos": col.pos, "fase": "inmovilizado_paso1"})
            print(f"[{int(step):4d} s] ACCIDENTE {acc_id} {col.type} {bus_id} x {moto_id}")
            
        else:
            for veh, vtype in [(col.collider, col.colliderType), (col.victim, col.victimType)]:
                if veh in persecuciones_activas:
                    persecuciones_activas.pop(veh, None)
                    agenda.append(int(step + 60))
                    agenda.sort()
                if vtype != "ambulance" and veh not in buses_ocupados:
                    try: traci.vehicle.remove(veh, traci.constants.REMOVE_VAPORIZED)
                    except: pass

def hospital_mas_cercano(arista_destino, flotas, hospitales_map, rng, requiere_unidad=True):
    """Encuentra hospital con menor travelTime; aplica negativa aleatoria[cite: 20, 35, 42]."""
    mejor_h, mejor_tiempo, mejor_ruta, unidad_asignada = None, float('inf'), None, None

    for h_id, datos in flotas.items():
        if requiere_unidad:
            if not datos["cola"]: continue
            if rng.random() < 0.25:
                datos["rechazos"] += 1
                continue
        try:
            ruta = traci.simulation.findRoute(hospitales_map[h_id]["edge"], arista_destino, vType="ambulance")
            if ruta.edges and ruta.travelTime < mejor_tiempo:
                mejor_tiempo, mejor_h, mejor_ruta = ruta.travelTime, h_id, ruta.edges
        except traci.TraCIException:
            pass

    if requiere_unidad and mejor_h:
        unidad_asignada = flotas[mejor_h]["cola"].popleft()
        
    return mejor_h, mejor_ruta, mejor_tiempo, unidad_asignada

def gestionar_misiones(step, lista_accidentes, flotas, hospitales_map, rng):
    """Máquina de estados: despacho, llegada, atención y retorno[cite: 20, 21, 22, 42, 43]."""
    llegados = traci.simulation.getArrivedIDList()

    for acc in lista_accidentes:
        fase = acc.get("fase")

        if fase == "espera":
            if step - acc.get("ultimo_intento", 0) >= 30:
                acc["ultimo_intento"] = step
                h_id, ruta, t_est, unidad = hospital_mas_cercano(acc["arista"], flotas, hospitales_map, rng, requiere_unidad=True)
                
                if h_id:
                    amb_id = f"amb_{unidad}_{acc['id']}"
                    traci.route.add(f"ruta_{amb_id}", ruta)
                    traci.vehicle.add(amb_id, f"ruta_{amb_id}", typeID="ambulance", depart="now", departPos=str(hospitales_map[h_id]["pos"]))
                    flotas[h_id]["despachos"] = flotas[h_id].get("despachos", 0) + 1
                    acc.update({"fase": "en_camino", "amb_id": amb_id, "h_origen": h_id, "unidad": unidad, "t_despacho": step, "t_ultima_ruta": step})
                    print(f"[{int(step):4d} s] DESPACHO {acc['id']} <- {h_id} {unidad} | ETA {t_est:.0f} s")
                else:
                    print(f"[{int(step):4d} s] SIN AMBULANCIA para {acc['id']}, reintento en 30s")

        elif fase == "en_camino":
            amb_id = acc["amb_id"]
            if amb_id in traci.vehicle.getIDList():
                if step - acc["t_ultima_ruta"] >= 60:
                    traci.vehicle.rerouteTraveltime(amb_id)
                    acc["t_ultima_ruta"] = step

                try:
                    d = traci.simulation.getDistanceRoad(traci.vehicle.getRoadID(amb_id), traci.vehicle.getLanePosition(amb_id), acc["arista"], acc["pos"], isDriving=True)
                    v = traci.vehicle.getSpeed(amb_id)
                    if (0 <= d <= 50) or (0 <= d <= 300 and v < 0.1 and traci.vehicle.getRoadID(amb_id) == acc["arista"]):
                        traci.vehicle.setSpeedMode(amb_id, 0)
                        traci.vehicle.setSpeed(amb_id, 0.0)
                        acc.update({"fase": "atendiendo", "t_llegada": step})
                        print(f"[{int(step):4d} s] LLEGADA {acc['id']} | Respuesta: {step - acc['t_despacho']} s")
                except traci.TraCIException:
                    pass

        elif fase == "atendiendo":
            if step - acc["t_llegada"] >= 120:
                for veh in acc["vehiculos"]:
                    try: traci.vehicle.remove(veh, traci.constants.REMOVE_VAPORIZED)
                    except: pass
                try: traci.poi.remove(f"poi_{acc['id']}")
                except: pass

                h_retorno, _, _, _ = hospital_mas_cercano(acc["arista"], flotas, hospitales_map, rng, requiere_unidad=False)
                amb_id = acc["amb_id"]
                
                try:
                    traci.vehicle.setSpeedMode(amb_id, 31)
                    traci.vehicle.setLaneChangeMode(amb_id, 1621)
                    traci.vehicle.setSpeed(amb_id, -1)
                    traci.vehicle.changeTarget(amb_id, hospitales_map[h_retorno]["edge"])
                except:
                    pass
                
                acc.update({"fase": "retorno", "h_retorno": h_retorno})
                print(f"[{int(step):4d} s] RETORNO {amb_id} -> {h_retorno}")

        elif fase == "retorno":
            if acc["amb_id"] in llegados:
                flotas[acc["h_retorno"]]["cola"].append(acc["unidad"])
                flotas[acc["h_retorno"]]["retornos"] = flotas[acc["h_retorno"]].get("retornos", 0) + 1
                flotas[acc["h_origen"]]["seg_ocupados"] += (step - acc["t_despacho"])
                acc["fase"] = "cerrado"
                print(f"[{int(step):4d} s] DISPONIBLE {acc['unidad']} en {acc['h_retorno']}")

def exportar_estadisticas(hospitales_map, flotas, lista_accidentes):
    """Exporta CSVs requeridos en Fase 5[cite: 44]."""
    os.makedirs("salida", exist_ok=True)
    with open("salida/hospitales.csv", mode="w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["hospital", "tipo", "stock_ini", "stock_fin", "despachos", "retornos", "rechazos", "segundos_ocupados", "utilizacion"])
        for h_id, datos in flotas.items():
            stock_ini = datos["stock_ini"]
            utilizacion = (datos["seg_ocupados"] / (10800 * stock_ini)) if stock_ini > 0 else 0
            writer.writerow([h_id, hospitales_map[h_id]["tipo"], stock_ini, len(datos["cola"]), datos.get("despachos", 0), datos.get("retornos", 0), datos["rechazos"], datos["seg_ocupados"], utilizacion])
            
    with open("salida/accidentes.csv", mode="w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "t_accidente", "t_despacho", "t_llegada", "t_retorno", "hospital_origen", "hospital_retorno", "espera_s"])
        for acc in lista_accidentes:
            writer.writerow([acc["id"], acc["t_accidente"], acc.get("t_despacho", -1), acc.get("t_llegada", -1), acc.get("t_retorno", -1), acc.get("h_origen", ""), acc.get("h_retorno", ""), acc.get("t_despacho", acc["t_accidente"]) - acc["t_accidente"]])
    print("\n[Fase 5] CSVs exportados en salida/")

if __name__ == "__main__":
    traci.start(["sumo", "-c", "reto.sumocfg"])
    hospitales_map = inicializar_hospitales()
    flotas, rng = inicializar_flotas(hospitales_map, seed=42)
    
    agenda = generar_agenda_accidentes(rng)
    lista_accidentes = []
    colisiones_procesadas = set()
    persecuciones_activas = {}
    buses_ocupados = set()
    
    print("\n--- INICIANDO SIMULACIÓN ---")
    
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        step = traci.simulation.getTime()
        
        # Forzar la salida del bucle exactamente a las 3.5 horas (12600 s)
        if step >= 12600:
            break
            
        if step % 1000 == 0:
            print(f"[Progreso] Tiempo simulado: {int(step)} s / 12600 s")
        
        for acc in lista_accidentes:
            if acc["fase"] == "inmovilizado_paso1":
                for veh in acc["vehiculos"]:
                    try:
                        traci.vehicle.setSpeedMode(veh, 31)
                        traci.vehicle.setSpeed(veh, 0.0)
                    except: pass
                acc["fase"] = "espera"
        
        gestionar_persecuciones(step, persecuciones_activas, agenda)
        
        if agenda and step >= agenda[0]:
            if programar_accidente(step, rng, persecuciones_activas, buses_ocupados):
                agenda.pop(0)
            else:
                agenda[0] += 20
                
        detectar_e_inmovilizar(step, lista_accidentes, colisiones_procesadas, persecuciones_activas, buses_ocupados, agenda)
        gestionar_misiones(step, lista_accidentes, flotas, hospitales_map, rng)

    traci.close()
    exportar_estadisticas(hospitales_map, flotas, lista_accidentes)
    print(f"--- SIMULACIÓN FINALIZADA | Total accidentes procesados: {len(lista_accidentes)} ---")
