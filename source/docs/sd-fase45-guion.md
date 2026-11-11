# SD: guion de las fases 4 y 5 (mover los modos, bloques de enlace y bloque de arranque)

Estado: PREPARACION. El código y las pruebas están hechos; NADA se aplicó a la Pi ni a la SD. Diseño de origen: `TallerPlugins/docs-internal/SD-LAYOUT.md` (rama `sd-layout-design`), secciones C, D, F. Solo DWC 3.6.

Decisiones del dueño (2026-11-07), que mandan sobre el informe anterior:
1. SI se mueven los cinco archivos de modo. Se cambian las referencias directamente; NO hay reenvíos (sección 2.3).
2. El bloque `boot` en `config.g` SI va (G3).
3. Todo reemplazo en un archivo suyo: SIEMPRE con el diff delante, NUNCA automático.

Piezas (rama `sd-fase45` de WorkshopService y rama `sd-fase45` de TallerPlugins, worktrees en `_worktrees-agents/sd-fase45` y `sd-fase45-tp`):

| Pieza | Dónde |
|---|---|
| rutas de modo, UNA fuente (servicio) | `dsf/mode_paths.py` |
| rutas de modo, UNA fuente (plugins) | `vue/_shared/machine-modes.js` y `_shared36` (`MODES_DIR`, `MODE_FILES`, `AUTO_MODE_FILE`, `MODE_STATE_FILE`, `sdPath`, `modeFilePath`) |
| mover los modos + reescribir referencias + deshacer | `dsf/modes_move.py`, `dsf/test_modes_move.py`, fixtures `dsf/fixtures/sd_modes/` |
| bloques de enlace T1/T2 | `dsf/native_merge.py`, `dsf/test_native_merge.py`, fixtures `dsf/fixtures/sd_merge/` |
| guardas contra el desajuste | `test_modes_move.Paths` (servicio), `tests/test_mode_paths.py` (plugins) |

## 1. Dependencia declarada: el manifiesto (rama `sd-fase1`)

El manifiesto lo escribe otro agente y NO se duplica aquí. Lo único que este trabajo necesita de él es una lista `hooks` por plugin:

```
{ "id": "daemon-tail",                       // [a-z0-9-], único; varios bloques en un archivo se ordenan por id
  "file": "sys/daemon.g",                    // solo sys/daemon.g, homeall.g, homez.g (T1) o sys/config.g (T2)
  "target": "0:/sys/workshop/hooks/daemon-tail.g",   // macro del taller (sdFile) que el bloque llama
  "version": 1,
  "legacy": [ "regex de una línea" | ["regex línea 1", "regex línea 2"] ] }   // lo que el dueño tiene hoy y el bloque reemplaza EN SU LUGAR
```

La lee `native_merge.hooks_from_manifest`. Mientras `sd-fase1` no la publique rige `DEFAULT_HOOKS` (`daemon-tail`, `homeall-tail`, `homez-tail`, `boot`). Los archivos de modo y `hooks/*.g` deben figurar en `sdFiles` del plugin que los entrega (las plantillas de modo ya están re-ubicadas en el árbol de staging de Printing: `examples/WorkshopPrinting/sys/workshop/modes/*.g` y `.../sys/workshop/data/modestate.g`).

## 2. Fase 4: mover el sistema de modos

### 2.1 Destino

| Antes | Después |
|---|---|
| `sys/automodeselect.g`, `sys/modefff.g`, `sys/modelaser.g`, `sys/modecnc.g` | `sys/workshop/modes/` |
| `sys/modestate.g` (estado de ejecución que escribe `daemon.g`) | `sys/workshop/data/modestate.g` |

Lo que RRF/DWC llaman por nombre no se mueve (`config.g`, `daemon.g`, `homeall.g`, `homez.g`, `pause.g`, etc. y `macros/mode/select*.g`, que DWC lista como menú).

### 2.2 Lista exacta de referencias y cómo se resuelve cada una

Todas las referencias del informe anterior, con su tratamiento:

| Referencia | Resolución |
|---|---|
| `sys/config.g` (líneas de modo) | `modes_move` propone el diff (nuevas rutas); luego la fase 5 las reemplaza por el bloque `boot`. Son DOS diffs seguidos, ambos con aceptación |
| `sys/daemon.g`: `M98 modestate.g`, `M98 automodeselect.g` y las tres `echo >"0:/sys/modestate.g"` | `modes_move` propone el diff (cadenas con la ruta nueva). Cambio de rutas, no de lógica |
| `macros/mode/select{fff,laser,cnc}.g` (6 cadenas) | `modes_move` propone el diff |
| `automodeselect.g` (sus `M98` a `modestate`, `modelaser`, `modecnc`, `modefff`, incluso `P"modecnc.g"` relativo) | se reescribe al moverlo; el diff se ve en el mismo plan |
| `modelaser.g`, `modecnc.g`, `modefff.g` (hook `M98 ... zcal.g`) | se mueven byte a byte (el hook apunta a `sys/workshop/macros/zcal/`, no cambia) |
| cualquier OTRO archivo de `sys/` o `macros/` con la ruta vieja que no conozcamos | lo encuentra el escáner de referencias; se propone el diff. Si es T0 (pause, cancel, ...) NO se edita: se lista como "a mano" y el plan se niega a aplicarse hasta que el dueño lo resuelva |
| macros de `sys/workshop/` con la ruta vieja | se listan ("las actualiza el plugin"), el plan se niega a aplicarse |
| servicio `capabilities.py`, `capabilities_io.sd_listing`, `config_package.py`, `machine_height.py` | adaptados a `mode_paths`; `sd_listing` busca los modos en `sys/workshop/modes` (hecho y probado) |
| servicio `config_scan.py` | `MAX_DEPTH` 2 a 3 y `MAX_FILES` 16 a 24 (P1, hecho; prueba `ScanDepth` con la cadena config.g -> boot.g -> automodeselect -> modefff) |
| Printing `util.js` (`MODE_FILE`), `PelletFeed.vue`, `PelletFanAdd.vue`, `ExtruderConfig.vue` (los 2 árboles) | importan de `machine-modes.js` (`MODE_FILES`, `modeFilePath`) |
| Printing/_shared: filas `startup_row_modefile_*`, `startup_row_boot_missing`, plantillas del asistente (`wizardMode` escribe `fileexists("0:/sys/workshop/modes/mode<x>.g")`), plantillas de staging | rutas nuevas; textos `i18n` actualizados |
| Motors `advisor.js` / `Advisor.vue` (2 árboles) | `modeFileRel` sobre `MODES_DIR` |
| `callsAutoModeSelect` (tarjeta de modos, `_shared` y `_shared36`) | acepta la línea con la ruta nueva O el bloque `hook=boot` (P2); la ruta vieja ya no cuenta |
| Jog `19-startup.js` / `11-free.js` | `jogFreeDaemonHasFailsafe` acepta la línea O el bloque `hook=daemon-tail` (P2): la página no añade una segunda línea |
| WorkshopConfig (plugin detenido) y su fixture `real-machine` | NO adaptado (no está instalado; sus pruebas usan una copia del diseño viejo). Ver "Necesita al dueño" |

Guardas para no volver a desajustar: `test_modes_move.Paths.test_no_old_layout_literal_in_the_other_modules` (servicio) falla si un módulo escribe una ruta vieja; `tests/test_mode_paths.py` (plugins) falla si cualquier fuente fuera de `machine-modes.js` escribe una ruta vieja o respelea `sys/workshop/modes`, y exige que las dos copias de `machine-modes.js` sean idénticas.

### 2.3 Reenvíos: no hacen falta (decisión con evidencia)

- Un reenvío en `sys/modefff.g` es un archivo que los editores (Printing `changeLineMode`, `machine_height.hook`, los planes de calentadores de cama) modificarían EN LUGAR del real: fallan con "línea no encontrada" o ensucian el reenvío.
- `sd_listing` y las filas de arranque detectan los modos por nombre; con reenvío verían modos que no existen.
- Alarga la cadena de `M98` más de lo que `config_scan` sigue.
- El dueño no mantiene compatibilidad con versiones viejas, y los llamadores de las rutas viejas que SI existen son archivos suyos que ya salen en el escáner y se arreglan con diff en la misma sesión.
- Riesgo que sí queda, y por eso el escáner: un llamador externo que no esté en `sys/` ni `macros/` (por ejemplo, algo de LightBurn). Del lado del taller no se encontró ninguno que llame a los archivos de modo; `airon.g` y `airoff.g` (los de LightBurn) no son parte de esta fase. Si el dueño sabe de uno, se avisa antes del día.
- Si en el día aparece un llamador inesperado que no se pueda arreglar en el momento: reenvío mínimo y TEMPORAL de UNA línea solo para `automodeselect.g` (`M98 P"0:/sys/workshop/modes/automodeselect.g"`), anotado en la bitácora y retirado en la misma semana. Nunca para `modefff/modelaser/modecnc/modestate`.

### 2.4 Cómo trabaja `modes_move`

Dry-run por defecto (no tiene ruta de escritura); `--apply` exige `--machine-off --accept --backup-dir`. Para cada archivo del movimiento: `move` (nuevo = viejo con las referencias reescritas), `done`, `absent` (la máquina no tiene ese modo: no es error) o `conflict` (existen viejo y nuevo: no se mueve). Para el resto: `rewrite` (diff) o `manual` (T0 / de plugin). Se niega a aplicar con cualquier `conflict` o `manual`, con la placa ocupada, sin aceptación, o si un archivo cambió desde el plan. Orden de escritura: nuevos primero (con relectura), luego ediciones, al final se borran los viejos; antes copia cada byte viejo a `--backup-dir` y escribe `modes-move-journal.json`. `--undo` restaura los bytes exactos y quita las copias nuevas que no hayan cambiado (si el dueño editó una copia nueva, la deja y lo avisa).

## 3. Fase 5: bloques de enlace T1 y bloque de arranque T2

Política (SD-LAYOUT D.3): T0 nunca se toca; T1 (`daemon.g`, `homeall.g`, `homez.g`) y T2 (`config.g`) reciben un bloque de 4 líneas marcado que solo llama a un macro del taller:

```
; >>> WORKSHOP hook=daemon-tail v=1 sha=1a2b3c4d  (managed block: change the file outside these lines)
if fileexists("0:/sys/workshop/hooks/daemon-tail.g")
    M98 P"0:/sys/workshop/hooks/daemon-tail.g"
; <<< WORKSHOP hook=daemon-tail
```

`sha=` cubre las líneas del cuerpo (un hash no puede cubrir la línea que lo contiene). Cómo trata `native_merge` cada estado (todo con pruebas):

| Estado del archivo | Resultado |
|---|---|
| líneas antiguas sin marcas (`jogFreeFailsafe`, `zbedref`, las líneas de modo de `config.g`, con la ruta vieja o la nueva) | `replace-legacy`: sustituye en su sitio por el bloque; exige aceptación; el diff muestra `-` lo viejo y `+` el bloque |
| línea antigua sangrada dentro de un `if`/bucle | se rechaza: se cambia a mano |
| sin bloque | `insert` al final (ordenado por id si hay otros) |
| bloque correcto | `unchanged` |
| bloque con otra versión | `update` (solo cambia el bloque) |
| bloque editado por dentro | `skip` ("drift"); solo con `--resolve replace` (diff) o `adopt` |
| marca suelta, bloque duplicado, orden invertido, anidados | `markers-broken`: no cambia nada |
| ya sin marcas pero una línea activa llama al macro | `target-referenced`: es del dueño |
| archivo ausente | `daemon.g` se crea con cabecera; los otros NO se crean |
| BOM, CRLF/LF, sin salto final, líneas de más de 255 | se conservan los bytes; las largas se avisan |
| desinstalar | quita solo nuestro bloque; instalar y desinstalar devuelve los bytes originales |

Escritura: solo `apply_plan` (atómico), que se niega con la placa ocupada, archivo cambiado desde el plan, sin aceptación o relectura distinta, y guarda los bytes viejos antes. La CLI con `--apply` exige `--machine-off --accept --only <archivo> --backup-dir`: UN archivo por vez. (`config.commit` aún no tiene un tipo de plan para bloques: la CLI es el camino provisional y `native_merge.plan_*` es la parte pura que se enchufará.)

Precondiciones: P1 (`config_scan` profundidad 3), P2 (lectores de Jog y de la tarjeta de modos aceptan el bloque) y P3 (los macros destino existen y la ruta de modos en `boot.g` es la nueva) están HECHAS en código y probadas. P4 queda como verificación del guion (paso 17).

## 4. Guion de ejecución (dueño presente, máquina apagada)

Reglas: dueño presente, fuente de motores apagada, nadie junto al láser, mano en la parada de emergencia desde el paso 21. Nada se aplica sin que el dueño haya leído el diff de ESE archivo y diga sí; cada "sí" se anota. Si algo no coincide con lo esperado: se PARA y se hace rollback (sección 5). Los pasos 1 a 11 no modifican la SD.

### 4.A Antes del día (PC)

1. Servicio: `cd dsf && python -m unittest test_modes_move test_native_merge test_config_package test_capabilities test_machine_height test_machine_beds test_machine_bed_edit` en verde. Plugins: `python -m unittest tests.test_mode_paths` y los `node` de `tests/machine-modes`, `startup-guide`, `startup-jog` y de Printing y Motors en verde.
2. Publicar e instalar ANTES (proceso normal de release, no parte de este guion) el servicio con `mode_paths`/`config_scan` y los plugins Printing, Motors, Jog y los `_shared` con las rutas nuevas, junto con los macros destino `sys/workshop/hooks/{daemon-tail,homeall-tail,homez-tail,boot}.g` (anexo A) y las plantillas de modo en su nueva ubicación. Sin eso, no se sigue. Observación: con el servicio nuevo instalado y los modos aún en `sys/`, la detección de modos devuelve "ninguno" hasta que se mueva; por eso se instala y se mueve el mismo día, con el dueño presente.
3. P4: abrir el fuente de RRF 3.5/3.6 y anotar el límite de anidación de macros (estructura de la pila de archivos de `GCodes`; no está verificado). La cadena de arranque que tendrá la máquina es config.g -> boot.g -> automodeselect.g -> modefff.g -> zcal.g.

### 4.B El día

4. Estado inicial: sin trabajo, sin macro, sin pausa, motores sin tensión. Anotar el tamaño actual de `eventlog.txt` (solo lectura por SSH).
5. Copia de seguridad (Fase 0): `tar` de `sys/`, `macros/`, `sys/workshop/{config,data,zones}` a `~/sd-backup/layout-<fecha>/`, `sha256sum` de cada archivo y el `config.snapshot` de lo nativo en `config-history`. Comprobar con `tar tf`. Sesión SSH abierta todo el día.
6. Extraer SOLO a una carpeta de trabajo `~/scratch/dry/` (copia, no la SD) lo que los dry-runs leen: `sys/{config,daemon,homeall,homez,automodeselect,modefff,modelaser,modecnc,modestate}.g`, `macros/mode/`, y el resto de `macros/` (para que el escáner de referencias lo vea). `pause.g`, `resume.g`, `cancel.g`, `stop.g`, `homex.g`, `homey.g`, etc. NO se copian a propósito.
   - Atención: si el escáner no ve un archivo T0 con una referencia vieja, no la reporta. Por eso, antes, en la SD real y solo lectura: `grep -lE "modestate|automodeselect|modefff|modelaser|modecnc" /opt/dsf/sd/sys/*.g /opt/dsf/sd/macros -r` y anotar qué archivos aparecen. Si sale algún T0, el dueño lo edita a mano en el paso 14.
7. Dry-run de la fase 4 sobre la copia: `python3 modes_move.py --root ~/scratch/dry` (la ruta del módulo se verifica con `ls` antes; se puede copiar el `.py` suelto, nada se instala). Guardar la salida.
8. El dueño LEE el plan completo. Esperado: 5 `MOVE` (o menos si no tiene un modo), 4 o más `REWRITE` (`config.g`, `daemon.g`, `select*.g`) y 0 `manual` ni `conflict`. Cualquier `manual` o `conflict` se resuelve antes de seguir. Los diffs de `daemon.g` solo deben cambiar cadenas de ruta (3 `echo >` y 2 `M98`); si el diff toca otra cosa, parar.
9. Dry-run de la fase 5 sobre la copia YA con la fase 4 simulada: aplicar `modes_move --apply` solo sobre `~/scratch/dry` (es una copia) y luego `python3 native_merge.py --root ~/scratch/dry`. Esperado: `daemon.g` `replace-legacy` (1 línea `jogFreeFailsafe` por 4), `homeall.g` y `homez.g` `replace-legacy` (`zbedref`), `config.g` `replace-legacy` (las 4 líneas de modo y `workplaces`, por el bloque `boot`, en el mismo sitio). Un `legacy-nested` o `markers-broken` = parar.
10. El dueño decide por archivo: aplicar / omitir. Anotar. Sin un sí claro, no se aplica.
11. Encender solo la alimentación de control si hace falta que la placa responda; motores apagados.

Fase 4 en la SD real:

12. `python3 modes_move.py --root /opt/dsf/sd` (dry-run otra vez, ahora sobre la SD real; el dueño vuelve a ver el diff real, no el de la copia). Debe coincidir con el del paso 7.
13. Aplicar: `python3 modes_move.py --root /opt/dsf/sd --apply --machine-off --accept --backup-dir ~/sd-backup/layout-<fecha>/modes` (HIPOTESIS: si el usuario de login no puede escribir en `/opt/dsf/sd`, se decide con el dueño cómo; no se usan credenciales en este guion). Imprime `written: N file(s)`. NO reiniciar todavía.
14. Verificar: `python3 modes_move.py --root /opt/dsf/sd` debe dar solo `DONE` y `ABSENT`; `grep -rE "sys/(modestate|automodeselect|modefff|modelaser|modecnc)\.g" /opt/dsf/sd/sys /opt/dsf/sd/macros` debe salir vacío salvo `*.bak*`. Si hay un T0 con referencia, el dueño lo edita a mano ahora (el diff del plan es lo que cambia) y se vuelve a verificar.

Fase 5, un archivo por vez, en este orden: `daemon.g`, `homeall.g`, `homez.g`, `config.g`. Para cada uno:

15. Dry-run del archivo: `python3 native_merge.py --root /opt/dsf/sd --only sys/<archivo>`; el dueño lee el diff y dice sí o no.
16. Aplicar: `python3 native_merge.py --root /opt/dsf/sd --only sys/<archivo> --apply --machine-off --accept --backup-dir ~/sd-backup/layout-<fecha>/hooks`. Verificar: el mismo comando sin `--apply` ahora dice `unchanged`; anotar `sha256sum`; los T0 (pause, resume, cancel, stop, homex, homey, bed, mesh, deployprobe, retractprobe) con `sha256sum` IGUAL al del paso 5 (salvo uno que el dueño haya editado en el paso 14, anotado).
   - Tras `daemon.g`: esperar 2 minutos y leer `eventlog.txt`: sin "Macro file ... not found", sin variable desconocida; la fila de Jog en verde. Anotar si el ciclo de `daemon.g` se nota (carga de la placa).
   - Tras `config.g`: NO reiniciar todavía.

Verificación del límite de anidación y arranque (P4) con rollback:

17. Con `config.g` listo y los modos ya movidos, antes de reiniciar: tener abierta en otra ventana la orden de rollback de `config.g` (sección 5) con la ruta del backup ya escrita. Reiniciar la placa (`M999`) y observar la consola de DWC.
18. Éxito si: sin error de arranque, sin "stack"/"too many nested macros"/"Macro file not found" en `eventlog.txt`; `global.selectedMode` existe con el modo esperado; el Workbench muestra las zonas (`workplaces.g` cargó); `daemon.g` da vueltas sin avisos. Anotar el nivel de anidación que tolera: si la placa llegó hasta `zcal.g` sin quejas, la cadena de 5 niveles cabe.
19. Fracaso (cualquier error de anidación o arranque): rollback inmediato de `config.g` (sección 5, fila 2) y `M999`; el bloque `boot` NO se queda. En ese caso se deja `config.g` con las líneas de modo con ruta nueva (el diff de `modes_move`) y se anota para decidir; el resto de los bloques (`daemon.g`, homing) pueden seguir.
20. Prueba de modos SIN tensión de motores: `macros/mode/selectlaser.g`, `selectcnc.g`, `selectfff.g`; tras cada una leer `state.machineMode` y que `sys/workshop/data/modestate.g` cambió (la escribe `daemon.g`). Volver al modo normal.

Prueba de homing (con tensión de motores, mano en la parada de emergencia):

21. Homing X, luego Y (`homex.g`/`homey.g` no se tocaron), luego Z con `homez.g`: confirmar que `zbedref.g` corrió (consola sin avisos) y que el movimiento es el de siempre. Después `homeall.g` completo con el mismo criterio. Cualquier movimiento distinto: parada de emergencia y rollback.
22. Pausa / reanudar / cancelar / parar con un trabajo corto inofensivo: el láser o el husillo se apagan (`M5`) y las ramas por `global.selectedMode` funcionan (sin "variable desconocida"). Los hash de los T0 siguen iguales.
23. Guardia del láser: arrancar el `cuts.gcode` regenerado por el Workbench y comprobar que la línea 4 resuelve a `guard/cutguard.g` (cierra A.1.3).
24. Páginas: abrir Printing (configurar zonas: debe leer `sys/workshop/modes/modefff.g`, hacer una edición reversible con vista previa y comprobar que quedó el `.bak-<fecha>` junto al archivo nuevo), Máquina > Altura (hook de `zcal` sobre los archivos nuevos), Motores > Asesor, y la tarjeta de modos (fila de arranque en verde con el bloque `boot`). Cualquier fila roja = anotar.
25. Bitácora de la sesión: fecha, hash antes y después de cada archivo, decisiones del dueño, resultado de cada prueba. Dejar `~/sd-backup/layout-<fecha>/`.

## 5. Rollback

| Qué falló | Qué hacer |
|---|---|
| Un archivo de la fase 5, en cualquier momento | `cp ~/sd-backup/layout-<fecha>/hooks/sys/<archivo> /opt/dsf/sd/sys/<archivo>` (copia exacta que guardó `--backup-dir`); comprobar `sha256sum` igual al del paso 5; si fue `config.g`, `M999` |
| `config.g` con el bloque `boot` impide arrancar o excede la anidación | restaurar `config.g` del backup `hooks` y `M999`. Si `config.g` falta del todo, DSF cae a `config.g.bak` (pero NO si solo tiene un error) |
| Toda la fase 4 | `python3 modes_move.py --root /opt/dsf/sd --undo --machine-off --accept --backup-dir ~/sd-backup/layout-<fecha>/modes` restaura los bytes exactos de los 5 archivos y de los editados, y quita las copias nuevas que no hayan cambiado (las que el dueño editó después, las deja y las nombra). Después, si ya se había aplicado la fase 5 sobre `config.g`, restaurar este también (fila 1) |
| Orden de rollback completo | primero la fase 5 (`config.g`, `homez.g`, `homeall.g`, `daemon.g`, restaurando del backup `hooks`), luego la fase 4 (`--undo`), luego `M999`. Es el orden inverso al de aplicación |
| Todo | `tar` de `sys/` y `macros/` de `~/sd-backup/layout-<fecha>/` y la copia diaria del taller |
| Un plugin se desinstala | el `M98` del bloque tiene `fileexists`: no da error; se quita con `native_merge --remove` tras ver el diff |

Los plugins del lado del navegador (rutas nuevas) no se revierten con la SD: si se hace rollback de la fase 4 hay que volver a instalar las versiones anteriores de Printing, Motors, Jog y el servicio. Por eso la instalación del paso 2 y el movimiento del paso 13 son del mismo día.

## Anexo A. Contenido esperado de los macros destino (los entregan el manifiesto y los plugins, no este repo)

- `sys/workshop/hooks/daemon-tail.g`: las globales que `daemon.g` declara hoy en línea si las lee otro macro (`if !exists(...)`), la lógica de apagado tras el trabajo y la llamada `M98 P"0:/sys/workshop/macros/work/jogFreeFailsafe.g"`. El bloque de `daemon.g` solo se instala cuando este archivo ya existe (si no, se pierde el failsafe).
- `sys/workshop/hooks/homeall-tail.g`, `homez-tail.g`: `M98 P"0:/sys/workshop/macros/zbedref.g"` con `if fileexists`, igual que la línea que reemplazan (el bloque ocupa el mismo lugar).
- `sys/workshop/hooks/boot.g`: reproduce las líneas de `config.g` con las rutas NUEVAS: `if !exists(global.selectedMode)` / `M98 P"0:/sys/workshop/data/modestate.g"` / `M98 P"0:/sys/workshop/modes/automodeselect.g"` / `M98 P"0:/sys/workshop/macros/work/workplaces.g"`, cada llamada con `fileexists`.

## Anexo B. Lo que necesita al dueño

1. WorkshopConfig (plugin detenido): no se adaptó a las rutas nuevas ni su fixture `real-machine`. Si algún día se reinstala, hay que hacerlo (4 literales en `Configurator.vue`, `rules/workshop.js`, `files-lint.js`). ¿Se adapta ahora o queda detenido?
2. Un llamador externo a las rutas viejas que yo no vea (LightBurn u otra herramienta): si lo conoce, decirlo antes del día; si no, el escáner lo detecta solo dentro de `sys/` y `macros/`.
3. Cómo se escribe en `/opt/dsf/sd` desde SSH (permisos del usuario de login).
4. `modestate.g` en `sys/workshop/data/` es una consecuencia de G2: confirmar. `daemon.g` lo escribe con `echo >`; la ruta nueva está dentro de `0:/sys/workshop`, sin problema de AppArmor por estar bajo `sys`.
5. Confirmar el orden: fase 4 y 5 el mismo día, un solo `M999` después de `config.g` (el guion lo asume).
6. Los plugins de Printing, Motors y Jog y el servicio deben publicarse (release) antes del día; ese proceso no está en este guion.
