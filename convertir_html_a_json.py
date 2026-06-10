# Convierte tests HTML (formatos PLATAFORMA, questions, Z.AI, TIPO, ESTUDIO, FALTAS)
# al JSON que consume entreno-oral. Uso:
#   python convertir_html_a_json.py                     -> convierte todo lo de ./PARA CONVERTIR
#   python convertir_html_a_json.py "carpeta o archivo" -> convierte lo indicado
# Salida: ./bancos/<nombre>.json + index.json actualizado (dedupe interno por enunciado)

import io, json, os, re, subprocess, sys, tempfile, html as htmlmod

SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bancos')

def limpiar_html(txt):
    if not txt: return None
    txt = re.sub(r'<[^>]+>', ' ', txt)
    txt = htmlmod.unescape(txt)
    txt = re.sub(r'\s+', ' ', txt).strip()
    return txt or None

def extraer_arrays(texto, nombre_var):
    """Devuelve cada array JSON asignado a nombre_var, por equilibrado de corchetes."""
    arrays = []
    for m in re.finditer(r'(?:(?:const|let|var)\s+)?' + nombre_var + r'\s*=\s*\[', texto):
        ini = m.end() - 1
        nivel, en_str, esc = 0, None, False
        for i in range(ini, len(texto)):
            c = texto[i]
            if en_str:
                if esc: esc = False
                elif c == '\\': esc = True
                elif c == en_str: en_str = None
            elif c in '"\'': en_str = c
            elif c == '[': nivel += 1
            elif c == ']':
                nivel -= 1
                if nivel == 0:
                    arrays.append(texto[ini:i+1]); break
    return arrays

def parsear(crudo):
    try:
        return json.loads(crudo)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(re.sub(r',\s*([\]}])', r'\1', crudo))  # comas finales
    except json.JSONDecodeError:
        # objeto JavaScript (claves sin comillas, comillas simples): evaluar con Node
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
            f.write('console.log(JSON.stringify(eval("(" + require("fs").readFileSync(%s, "utf8") + ")")))'
                    % json.dumps(f.name + '.data'))
            js = f.name
        io.open(js + '.data', 'w', encoding='utf-8').write(crudo)
        try:
            out = subprocess.run(['node', js], capture_output=True, text=True, encoding='utf-8')
            if out.returncode != 0:
                raise ValueError('Node no pudo evaluar el array: ' + out.stderr[:200])
            return json.loads(out.stdout)
        finally:
            os.unlink(js); os.unlink(js + '.data')

FALTAS_TIPOS = ['Muy grave', 'Grave', 'Leve']

def convertir_pregunta(q, tema):
    if 'enunciado' in q:                      # formato PLATAFORMA
        opciones = [o['texto'] for o in q['opciones']]
        correcta = next(i for i, o in enumerate(q['opciones']) if o.get('correcta'))
        enunciado = q['enunciado']
        explicacion = limpiar_html(q.get('explicacion'))
    elif 'texto' in q:                        # formato ESTUDIO {texto,opciones,correcta,exp}
        opciones = q['opciones']
        correcta = q['correcta']
        enunciado = q['texto']
        explicacion = limpiar_html(q.get('exp'))
    elif 'text' in q and 'options' in q:      # formato Z.AI {text,options,correct,explanation}
        opciones = q['options']
        correcta = q['correct']
        enunciado = q['text']
        explicacion = (q.get('explanation') or '').strip() or None
    elif 'q' in q:                            # formato TIPO {q,a,c,e}
        opciones = q['a']
        correcta = q['c']
        enunciado = q['q']
        explicacion = limpiar_html(q.get('e'))
    elif 'answer' in q:                       # formato FALTAS (clasificacion)
        opciones = FALTAS_TIPOS[:]
        correcta = FALTAS_TIPOS.index(q['answer'])
        enunciado = '¿Cómo se califica esta falta? ' + q['text']
        explicacion = (q.get('explanation') or '').strip() or None
    else:                                     # formato questions
        opciones = q['options']
        correcta = q['correctIndex']
        enunciado = q['question']
        explicacion = (q.get('explanation') or '').strip() or None
    enunciado = re.sub(r'^\d+[.)]\s*', '', enunciado.strip())
    out = {'pregunta': enunciado, 'opciones': opciones, 'correcta': correcta, 'tema': tema}
    if explicacion: out['explicacion'] = explicacion
    return out

def convertir_archivo(ruta):
    texto = io.open(ruta, encoding='utf-8', errors='replace').read()
    crudos = (extraer_arrays(texto, 'PREGUNTAS') or extraer_arrays(texto, 'questions')
              or extraer_arrays(texto, 'QUESTIONS'))
    if not crudos:
        return None, 'sin array de preguntas reconocible'
    nombre = os.path.splitext(os.path.basename(ruta))[0]
    nombre = re.sub(r'\s*\(.*?\)\s*', ' ', nombre)
    nombre = re.sub(r'[_]+', ' ', nombre)
    nombre = re.sub(r'\s{2,}', ' ', nombre).strip()
    preguntas, vistas = [], set()
    for crudo in crudos:
        for q in parsear(crudo):
            try:
                p = convertir_pregunta(q, nombre)
            except (KeyError, StopIteration, ValueError):
                continue
            clave = re.sub(r'\W+', '', p['pregunta'].lower())
            if clave in vistas: continue
            vistas.add(clave)
            if (isinstance(p['correcta'], int) and 2 <= len(p['opciones']) <= 4
                    and 0 <= p['correcta'] < len(p['opciones'])):
                preguntas.append(p)
    return (nombre, preguntas), None

CARPETA_ENTRADA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'PARA CONVERTIR')

def expandir_rutas(args):
    rutas = []
    for a in (args or [CARPETA_ENTRADA]):
        if os.path.isdir(a):
            rutas += [os.path.join(a, f) for f in sorted(os.listdir(a))
                      if f.lower().endswith(('.html', '.htm'))]
        else:
            rutas.append(a)
    return rutas

if __name__ == '__main__':
    os.makedirs(SALIDA, exist_ok=True)
    os.makedirs(CARPETA_ENTRADA, exist_ok=True)
    ruta_indice = os.path.join(SALIDA, 'index.json')
    try:
        indice = json.load(io.open(ruta_indice, encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        indice = []
    rutas = expandir_rutas(sys.argv[1:])
    if not rutas:
        print(f'No hay archivos HTML en "{CARPETA_ENTRADA}". Pon ahí los tests y vuelve a ejecutar.')
        sys.exit(0)
    for ruta in rutas:
        res, err = convertir_archivo(ruta)
        if err:
            print(f'SALTADO {os.path.basename(ruta)}: {err}'); continue
        nombre, preguntas = res
        if not preguntas:
            print(f'SALTADO {os.path.basename(ruta)}: 0 preguntas convertibles'); continue
        archivo = re.sub(r'[^\w-]+', '_', nombre.lower()).strip('_') + '.json'
        with io.open(os.path.join(SALIDA, archivo), 'w', encoding='utf-8') as f:
            json.dump(preguntas, f, ensure_ascii=False, indent=1)
        indice = [e for e in indice if e['archivo'] != archivo]
        indice.append({'nombre': nombre, 'archivo': archivo, 'preguntas': len(preguntas)})
        print(f'OK {archivo}: {len(preguntas)} preguntas')
    with io.open(ruta_indice, 'w', encoding='utf-8') as f:
        json.dump(indice, f, ensure_ascii=False, indent=1)
    print(f'\nindex.json con {len(indice)} bancos en {SALIDA}')
