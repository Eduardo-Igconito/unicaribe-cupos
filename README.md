# Bot de cupos Unicaribe

Revisa cada 15 minutos el horario de clases de Conecta y manda un mensaje por Telegram cuando una de las materias de `config.json` tiene cupo disponible.

No usa la cuenta del estudiante. Consulta el horario público de Conecta, el mismo que se ve sin iniciar sesión, que ya trae capacidad, inscritos y lugares restantes de cada sección.

## Cómo avisa

- Cuando aparece una sección nueva con cupo, o una que estaba llena se libera, llega un mensaje con la materia, el CRN, el campus, el horario y los lugares que quedan.
- Si la sección se vuelve a llenar y luego se libera otra vez, vuelve a avisar.
- La primera vez que corre manda un mensaje de "bot activo" con lo que está vigilando.

## Configurar las materias

En `config.json`:

```json
{
  "periodos": "auto",
  "excluir_periodos_que_contengan": ["MASTER"],
  "materias": [
    { "materia": "INF", "numero": "111" },
    { "materia": "MAT", "numero": "101", "campus": "SANTO DOMINGO", "modalidad": "VIRTUAL", "seccion": ["400", "401"] }
  ]
}
```

- `materia` y `numero` son la clave de la materia, por ejemplo `INF 111`.
- `campus`, `modalidad` y `seccion` son opcionales y sirven para filtrar.
- Con `"periodos": "auto"` revisa todos los períodos que todavía permiten inscripción. Si quieres fijar uno, pon su código, por ejemplo `["202611"]` para noviembre de 2026.

## Ponerlo a correr en GitHub (gratis)

1. **Crear el bot de Telegram.** En Telegram, habla con **@BotFather**, manda `/newbot` y copia el *token* que te da.
2. **Sacar el chat ID.** Escríbele cualquier cosa a tu bot nuevo y luego abre `https://api.telegram.org/bot<TOKEN>/getUpdates`. El número que aparece en `"chat":{"id": ...}` es el chat ID. Si el aviso debe llegar a varias personas, separa los IDs con comas. Cada persona tiene que escribirle al bot primero.
3. **Crear un repositorio en GitHub.** Mejor público, porque así los minutos de Actions no tienen límite. En el código no hay ninguna clave.
4. En el repo, entra en **Settings → Secrets and variables → Actions** y crea estos dos *secrets*:
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`
5. Sube esta carpeta al repo.
6. En la pestaña **Actions**, abre "Vigilar cupos" y dale a **Run workflow** para probarlo la primera vez. Después corre solo.

> GitHub no siempre respeta los 15 minutos exactos; a veces se atrasa un poco cuando sus servidores están cargados.

## Probar en la PC

```bash
python bot.py
```

Si no están las variables `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID`, imprime los avisos en la consola en vez de mandarlos.
