"""
Vigila el horario público de Conecta (Unicaribe) y avisa por Telegram
cuando una de las materias configuradas tiene cupo disponible.

No necesita la cuenta del estudiante: usa la consulta pública de horarios
de Banner (bwckschd), que es la misma que ve cualquiera sin iniciar sesión.

Uso:
    python bot.py            # revisa y avisa
    python bot.py --prueba   # manda un mensaje de prueba a Telegram
"""

import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://conecta.unicaribe.edu.do/PROD/"
INSCRIPCION = ("https://inscripcion_de_asignaturas.unicaribe.edu.do/StudentRegistrationSsb/"
               "ssb/registration/registerPostSignIn?mode=registration")
POCOS_CUPOS = 3
CARPETA = Path(__file__).parent
CONFIG = CARPETA / "config.json"
ESTADO = CARPETA / "estado.json"

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHATS = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]


class PortalCaido(Exception):
    pass


# ---------------------------------------------------------------- HTTP

def pedir(ruta, datos=None, intentos=3):
    url = BASE + ruta
    cuerpo = None
    if datos is not None:
        cuerpo = urllib.parse.urlencode(datos, doseq=True).encode()
    for intento in range(1, intentos + 1):
        try:
            req = urllib.request.Request(url, data=cuerpo, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) unicaribe-cupos",
            })
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            if intento == intentos:
                raise PortalCaido(f"{ruta}: {e}") from e
            time.sleep(5 * intento)


def limpiar(texto):
    texto = re.sub(r"<[^>]+>", " ", texto)
    return re.sub(r"\s+", " ", html.unescape(texto)).strip()


# ---------------------------------------------------------------- Banner

def periodos_abiertos():
    """Periodos que todavía permiten inscribirse (los que no dicen 'Ver solo')."""
    pagina = pedir("bwckschd.p_disp_dyn_sched")
    periodos = {}
    for valor, nombre in re.findall(r'<OPTION VALUE="(\d+)">([^<]+)</OPTION>', pagina, re.I):
        nombre = nombre.strip()
        if "ver solo" not in nombre.lower():
            periodos[valor] = nombre
    return periodos


def buscar_secciones(periodo, materia, numero):
    datos = [
        ("term_in", periodo),
        ("sel_subj", "dummy"), ("sel_day", "dummy"), ("sel_schd", "dummy"),
        ("sel_insm", "dummy"), ("sel_camp", "dummy"), ("sel_levl", "dummy"),
        ("sel_sess", "dummy"), ("sel_instr", "dummy"), ("sel_ptrm", "dummy"),
        ("sel_attr", "dummy"),
        ("sel_subj", materia), ("sel_crse", numero), ("sel_title", ""),
        ("sel_schd", "%"), ("sel_from_cred", ""), ("sel_to_cred", ""),
        ("sel_camp", "%"), ("sel_levl", "%"), ("sel_ptrm", "%"),
        ("sel_instr", "%"), ("sel_attr", "%"),
        ("begin_hh", "0"), ("begin_mi", "0"), ("begin_ap", "a"),
        ("end_hh", "0"), ("end_mi", "0"), ("end_ap", "a"),
    ]
    pagina = pedir("bwckschd.p_get_crse_unsec", datos)
    if "Listado de Horario de Clase" not in pagina and "ddtitle" not in pagina:
        raise PortalCaido(f"respuesta rara buscando {materia} {numero}")

    secciones = []
    for bloque in re.split(r'<th CLASS="ddtitle"', pagina, flags=re.I)[1:]:
        enc = re.search(r'crn_in=(\d+)">([^<]+)</a>', bloque)
        if not enc:
            continue
        crn, titulo = enc.group(1), html.unescape(enc.group(2)).strip()
        # "INGLES TECNICO I - 17223 - INF 111 - 400"
        partes = [p.strip() for p in titulo.split(" - ")]
        campus = re.search(r"([^>\n]+?)\s+Campus", bloque)
        # "Fechas de Inscripción: Ago 14, 2026 to Oct 07, 2026"
        inscripcion = re.search(r"Fechas de Inscripci[^<]*</SPAN>\s*[^<]*?\bto\s+([^<]+?)\s*<", bloque, re.I)
        celdas = [limpiar(c) for c in re.findall(r'<td CLASS="dddefault">(.*?)</td>', bloque, re.I | re.S)]
        # Fila de horario: Tipo, Hora, Días, Dónde, Rango, Tipo de horario, Instructores
        hora = celdas[1] if len(celdas) > 1 else ""
        dias = celdas[2] if len(celdas) > 2 else ""
        modalidad = celdas[5] if len(celdas) > 5 else ""
        profesor = celdas[6] if len(celdas) > 6 else ""
        secciones.append({
            "crn": crn,
            "nombre": partes[0] if partes else titulo,
            "clave": partes[2] if len(partes) > 2 else f"{materia} {numero}",
            "seccion": partes[3] if len(partes) > 3 else "",
            "campus": campus.group(1).strip() if campus else "",
            "inscripcion_hasta": inscripcion.group(1).strip() if inscripcion else "",
            "hora": hora,
            "dias": dias,
            "modalidad": modalidad,
            "profesor": re.sub(r"\s*\(\s*P\s*\)", "", profesor),
        })
    return secciones


def cupos(periodo, crn):
    pagina = pedir(f"bwckschd.p_disp_detail_sched?term_in={periodo}&crn_in={crn}")
    m = re.search(
        r'fieldlabeltext">Lugares</SPAN></th>\s*'
        r'<td CLASS="dddefault">(-?\d+)</td>\s*'
        r'<td CLASS="dddefault">(-?\d+)</td>\s*'
        r'<td CLASS="dddefault">(-?\d+)</td>',
        pagina, re.I)
    if not m:
        raise PortalCaido(f"no encontré los lugares del CRN {crn}")
    capacidad, inscritos, restante = map(int, m.groups())
    return capacidad, inscritos, restante


# ---------------------------------------------------------------- Telegram

def avisar(texto):
    if not TOKEN or not CHATS:
        print("[sin Telegram configurado]\n" + re.sub(r"<[^>]+>", "", texto) + "\n")
        return
    for chat in CHATS:
        datos = urllib.parse.urlencode({
            "chat_id": chat,
            "text": texto,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode()
        try:
            urllib.request.urlopen(f"https://api.telegram.org/bot{TOKEN}/sendMessage", datos, timeout=20)
        except Exception as e:
            print(f"No se pudo mandar el aviso a {chat}: {e}")


def mensaje_cupo(s):
    e = html.escape
    r = s["restante"]
    if r <= POCOS_CUPOS:
        cabecera = f"⚠️ <b>¡{'Último cupo' if r == 1 else f'Últimos {r} cupos'} para {e(s['periodo_nombre'])}!</b>"
    else:
        cabecera = f"🟢 <b>¡Hay cupo para {e(s['periodo_nombre'])}!</b>"
    lineas = [
        cabecera,
        f"<b>{e(s['nombre'])}</b> ({e(s['clave'])}-{e(s['seccion'])})",
        f"📅 Mes: <b>{e(s['periodo_nombre'])}</b>",
    ]
    if s["inscripcion_hasta"]:
        lineas.append(f"⏳ Inscripción hasta: {e(s['inscripcion_hasta'])}")
    lineas.append(f"CRN <code>{s['crn']}</code>")
    lugar = " · ".join(x for x in (s["campus"], s["modalidad"]) if x)
    if lugar:
        lineas.append(e(lugar))
    horario = " ".join(x for x in (s["dias"], s["hora"]) if x and x != "PA")
    if horario:
        lineas.append(e(horario))
    if s["profesor"] and s["profesor"] != "PA":
        lineas.append("Prof. " + e(s["profesor"]))
    lineas.append(f"Queda <b>1</b> de {s['capacidad']} lugares" if r == 1
                  else f"Quedan <b>{r}</b> de {s['capacidad']} lugares")
    lineas.append("")
    lineas.append(f'👉 <a href="{INSCRIPCION}">Inscribirme ahora</a> (pega el CRN en "Enter CRNs")')
    lineas.append(f'<a href="{BASE}bwckschd.p_disp_detail_sched?term_in={s["periodo"]}&crn_in={s["crn"]}">Ver detalle en Conecta</a>')
    return "\n".join(lineas)


# ---------------------------------------------------------------- principal

def coincide(seccion, filtro):
    if filtro.get("seccion") and seccion["seccion"].upper() not in [x.upper() for x in _lista(filtro["seccion"])]:
        return False
    if filtro.get("campus") and not any(c.upper() in seccion["campus"].upper() for c in _lista(filtro["campus"])):
        return False
    if filtro.get("modalidad") and not any(m.upper() in seccion["modalidad"].upper() for m in _lista(filtro["modalidad"])):
        return False
    return True


def _lista(valor):
    return valor if isinstance(valor, list) else [valor]


def main():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    materias = config["materias"]
    if not materias:
        print("No hay materias en config.json; no se revisa nada.")
        return
    if os.environ.get("GITHUB_ACTIONS") and not (TOKEN and CHATS):
        # Sin Telegram se guardaría el estado sin avisar a nadie y esos cupos ya no se notificarían.
        print("::warning::Faltan los secrets TELEGRAM_TOKEN / TELEGRAM_CHAT_ID; no se revisa nada.")
        return
    primera_vez = not ESTADO.exists()
    anterior = set(json.loads(ESTADO.read_text(encoding="utf-8")).get("con_cupo", [])) if not primera_vez else set()

    try:
        abiertos = periodos_abiertos()
        elegidos = config.get("periodos", "auto")
        if elegidos != "auto":
            abiertos = {p: abiertos.get(p, p) for p in _lista(elegidos)}
        excluir = [x.upper() for x in config.get("excluir_periodos_que_contengan", [])]
        abiertos = {p: n for p, n in abiertos.items() if not any(x in n.upper() for x in excluir)}
        print("Periodos abiertos:", ", ".join(abiertos.values()) or "ninguno")

        con_cupo = {}
        for periodo, periodo_nombre in abiertos.items():
            for filtro in materias:
                materia = filtro["materia"].upper().strip()
                numero = str(filtro.get("numero", "")).strip()
                for s in buscar_secciones(periodo, materia, numero):
                    if not coincide(s, filtro):
                        continue
                    capacidad, inscritos, restante = cupos(periodo, s["crn"])
                    print(f"  {periodo_nombre} | {s['clave']}-{s['seccion']} CRN {s['crn']} | {s['campus']} | {restante}/{capacidad}")
                    if restante > 0:
                        s.update(periodo=periodo, periodo_nombre=periodo_nombre,
                                 capacidad=capacidad, restante=restante)
                        con_cupo[f"{periodo}-{s['crn']}"] = s
                    time.sleep(0.5)  # no saturar el portal
    except PortalCaido as e:
        # Si el portal falla no se toca el estado; así no llegan avisos repetidos cuando vuelva.
        print(f"::warning::Conecta no respondió bien, se intenta en la próxima vuelta ({e})")
        return

    nuevos = [s for clave, s in con_cupo.items() if clave not in anterior]
    if primera_vez:
        vigiladas = ", ".join(f"{m['materia']} {m.get('numero', '')}".strip() for m in materias)
        avisar(f"🤖 Bot de cupos activo.\nVigilando: {html.escape(vigiladas)}\n"
               f"Periodos: {html.escape(', '.join(abiertos.values()) or 'ninguno abierto ahora')}")
    for s in nuevos:
        avisar(mensaje_cupo(s))
    print(f"Con cupo: {len(con_cupo)} | avisos nuevos: {len(nuevos)}")

    nuevo_estado = sorted(con_cupo)
    if primera_vez or set(nuevo_estado) != anterior:
        ESTADO.write_text(json.dumps({"con_cupo": nuevo_estado}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if "--prueba" in sys.argv:
        avisar("✅ Prueba del bot de cupos de Unicaribe. Si lees esto, Telegram está bien configurado.")
    else:
        main()
