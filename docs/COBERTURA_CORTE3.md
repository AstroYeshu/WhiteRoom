# Cobertura del corte 3: pruebas quitadas de `test_commands.py`

El corte 3 (`b31164c`) quitó 30 pruebas de `tests/test_commands.py`. Casi todas describían la interfaz vieja
(un mensaje por tarea, textos sin «Aviso ·»). Cada comportamiento pasó a `tests/test_vistas.py` (V) salvo donde se indica.

| # | Prueba quitada | Comportamiento | Cubierta ahora por |
|---|---|---|---|
| 1 | test_hoy_sin_nada | /hoy vacío | V: test_hoy_vacio_tiene_un_estado_cuidado |
| 2 | test_hoy_muestra_tareas_vencidas_de_hoy_y_recordatorios_de_hoy | secciones, vencidas, avisos de hoy | V: test_hoy_con_secciones_horas_cortas_y_bandeja |
| 3 | test_hoy_con_area_filtra_y_no_muestra_la_bandeja | filtro por área | V: mismo nombre |
| 4 | test_hoy_con_un_area_que_no_existe | área inexistente | V: mismo nombre |
| 5 | test_hoy_no_cuenta_la_bandeja_si_esta_vacia | sin línea de bandeja si está vacía | V: test_hoy_vacio_tiene_un_estado_cuidado (igualdad exacta) y NUEVA test_hoy_con_avisos_pero_sin_bandeja_no_menciona_la_bandeja |
| 6 | test_hoy_cerca_de_medianoche_... | día local termina a las 00:00 | V: mismo nombre (+ NUEVA test_hoy_un_aviso_a_las_00_00_exactas_ya_es_de_manana: el límite exacto de los avisos no estaba cubierto) |
| 7 | test_hoy_pasada_la_medianoche_ya_es_otro_dia | cambio de día | V: mismo nombre |
| 8 | test_pendientes_sin_tareas | lista vacía | V: mismo nombre |
| 9 | test_pendientes_un_mensaje_por_tarea_con_hecha_y_descartar | un mensaje por tarea | REEMPLAZADO por diseño (un solo mensaje): V: test_pendientes_es_un_solo_mensaje_con_lista_numerada_y_un_boton_por_numero y test_un_numero_muestra_la_tarea_... |
| 10 | test_pendientes_con_area | filtro por área | V: test_pendientes_con_area_la_pone_en_el_titulo, test_con_area_la_lista_actualizada_conserva_el_filtro |
| 11 | test_pendientes_con_un_area_que_no_existe | área inexistente | V: mismo nombre |
| 12 | test_pendientes_limita_la_lista_y_avisa | límite y «y N más» | V: test_pendientes_limita_a_10_y_avisa_cuantas_faltan |
| 13 | test_hecha_cierra_la_tarea_y_edita_el_mensaje | Hecha | V: test_hecha_cierra_esa_tarea_y_vuelve_a_la_lista_actualizada |
| 14 | test_descartar_es_soft_delete_con_motivo | Descartar | V: test_descartar_es_soft_delete_con_motivo_y_vuelve_a_la_lista |
| 15 | test_pulsar_dos_veces_o_en_otra_tarea_cerrada_no_da_error | doble pulsación / tarea ya cerrada | V: test_hecha_dos_veces_..., test_un_numero_de_una_tarea_ya_cerrada_..., test_hecha_sobre_una_tarea_descartada_afuera_no_la_pisa |
| 16 | test_hecha_cancela_los_avisos_de_preparacion | Hecha cancela avisos | V: mismo nombre |
| 17 | test_botones_de_tarea_mal_formados_o_inexistentes | ids malos | V: test_botones_de_pendientes_mal_formados_o_inexistentes_no_hacen_dano |
| 18 | test_recordatorios_sin_pendientes | vacío | V: mismo nombre |
| 19 | test_recordatorios_lista_pendientes_con_area_y_repeticion | lista | V: mismo nombre |
| 20 | test_los_detenidos_se_explican_en_lenguaje_claro | motivos | V: mismo nombre |
| 21 | test_un_codigo_desconocido_dice_motivo_desconocido_... | código desconocido solo al log | V: mismo nombre |
| 22 | test_recordatorios_limita_la_lista | límite | V: test_recordatorios_limita_cada_seccion |
| 23 | test_recordar_sin_texto_explica_como_usarlo | uso de /recordar | V: test_los_errores_de_uso_tienen_el_formato_de_aviso |
| 24 | test_tarea_sin_texto_explica_como_usarla | uso de /tarea | V: idem (solo prefijo «Aviso · Escribe /tarea») |
| 25 | test_nota_sin_texto_explica_como_usarla | uso de /nota | V: idem (solo prefijo) |
| 26 | test_areas_lista_y_marca_las_que_no_tienen_descripcion | /areas | V: mismo nombre |
| 27 | test_areas_no_lista_las_archivadas | /areas | V: mismo nombre |
| 28 | test_nuevaarea_sin_nombre_explica_como_usarla | uso de /nuevaarea | V: test_los_errores_de_uso_... (solo prefijo) |
| 29 | test_ayuda_lista_todos_los_comandos_y_no_la_papelera | /ayuda | V: test_ayuda_esta_agrupada_por_tipo_de_comando (texto exacto) |
| 30 | test_el_tiempo_de_un_dia_cercano_a_medianoche_usa_la_zona_del_usuario | filtro en hora local, no UTC | V: test_hoy_cerca_de_medianoche_... (23:59 local = 05:59 UTC del día siguiente) |

## Otras áreas pedidas
- Extraños: siguen en `test_commands.py::test_un_extrano_no_recibe_nada_ni_cambia_nada` (todos los comandos) y en V (/hoy, /pendientes,
  /recordatorios, /areas, /ayuda, y un botón de pendientes pulsado por un extraño).
- Escape de texto: V: test_pendientes_escapa_el_texto_del_usuario; NUEVA test_las_vistas_escapan_el_texto_del_usuario (/hoy y /recordatorios).
- Privacidad en logs: `test_commands.py::test_los_comandos_no_registran_el_texto_del_usuario`; NUEVA
  test_los_botones_de_pendientes_no_registran_el_texto_del_usuario (abrir, Hecha, Descartar, /areas, /hoy, /recordatorios).

## Mínimos de las pruebas nuevas, verificado con mutación
Sin escape en `esc` -> falla la de escape; el título en el log de Hecha -> falla la de privacidad; la línea de bandeja siempre -> falla la de
bandeja; `fire > day_end` (00:00 exactas) -> falla la de medianoche. Cada una la mata una prueba (los tres tipos de hueco eran de una sola prueba).
