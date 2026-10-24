# Purgatio

**Inventario visual y desinstalación unificada de software en Linux.**

Purgatio responde a dos preguntas que en Linux obligan a media docena de comandos:
«¿qué tengo instalado?» y «¿cómo se quita esto?». Reúne en una sola ventana lo que
instalaste con APT, Snap, Flatpak, pipx, npm, Cargo, Go, Homebrew, además de AppImages y binarios
sueltos que ningún gestor conoce. No hay lista que mantener a mano: se lee el estado
real del sistema en cada arranque.

![Purgatio](data/purgatio.svg)

## Qué hace

- **Un listado único** con buscador, filtro por origen y «solo manuales» activado por
  defecto (las 2.400 librerías de APT no te tapan las 76 apps que instalaste tú).
- **Tamaño real** de cada cosa, para saber qué ocupa de verdad.
- **Desinstalar con confirmación**: muestra el comando exacto y, en APT, qué otros
  paquetes se llevaría por delante (simulación), antes de ejecutarlo; pide la contraseña con el diálogo nativo del sistema (polkit/pkexec).
- **Limpieza de restos**: paquetes huérfanos de APT, revisiones antiguas de Snap y
  runtimes de Flatpak que ya no usa nada.
- **Historial**: lee `/var/log/apt/history.log` y te dice qué se instaló, cuándo y con
  qué orden. Ideal para ese paquete del que ya no te acordabas.
- **Exportar inventario** a Markdown para guardarlo o consultarlo sin abrir la app.
- **CLI** para todo lo anterior, útil para scripts y para depurar.

## Instalación

Requiere Ubuntu/GNOME con GTK 4 y Libadwaita (en Ubuntu 26.04 vienen de serie) y
`python3-gi` + `python3-apt`.

```bash
./install.sh          # enlaza el comando y crea la entrada de menú
purgatio              # abre la interfaz
```

Sin instalar nada:

```bash
./bin/purgatio
python3 -m purgatio
```

Desinstalar la integración: `./install.sh uninstall`.

## Uso rápido

```bash
purgatio list --source snap          # qué snaps hay
purgatio list --all --source apt     # incluye dependencias
purgatio list --search bittorrent
purgatio history --limit 20          # qué se instaló y cuándo
purgatio orphans                     # restos y espacio recuperable
purgatio info flatpak:com.obsproject.Studio
purgatio remove apt:htop --dry-run   # enseña el comando sin ejecutarlo
purgatio export --out ~/inventario.md
```

## Cómo está hecho

```
purgatio/
├── core/
│   ├── models.py        # Package / Orphan / Source: modelo común
│   ├── registry.py      # escaneo en paralelo de todos los backends
│   ├── runner.py        # ejecución con pkexec + streaming de salida
│   ├── history.py       # parser de /var/log/apt/history.log(.gz)
│   ├── inventory.py     # exportación Markdown/JSON
│   └── backends/        # un módulo por gestor
│       ├── apt_backend.py      # python-apt (sin parsear consola)
│       ├── snap_backend.py
│       ├── flatpak_backend.py
│       ├── pipx_backend.py
│       ├── npm_backend.py      # npm + cargo
│       ├── go_backend.py       # go install
│       ├── brew_backend.py     # Homebrew
│       └── manual_backend.py   # AppImages, ~/.local/bin, restos .old
└── ui/                  # GTK4 + Libadwaita
```

**Añadir una fuente nueva** = heredar `Backend`, implementar `list_packages()` y
`removal_argv()`, y registrarla en `core/registry.py`. La interfaz no cambia.

## Criterios de seguridad

- Nada se ejecuta sin confirmación explícita, y el comando exacto se muestra antes.
- Los paquetes esenciales o de prioridad `required` de APT, y los componentes de Snap
  (`core*`, `snapd`, `gnome-*`, `mesa-*`…), están marcados y no se ofrecen para quitar.
- Los backends nunca elevan privilegios por su cuenta: solo devuelven la orden; la
  elevación ocurre con `pkexec` en el momento de ejecutar.
- Un backend que falla no tumba el escaneo: se avisa y el resto sigue funcionando.

## Estado y siguientes pasos

Versión 0.1.0, funcional y probada contra el sistema real. Ideas pendientes:

- Empaquetar como `.deb` y publicar en Flathub (irónico: una app para desinstalar
  Flatpaks, empaquetada como Flatpak, necesitaría hablar con el Flatpak del host).
- Filtro «instalado en los últimos N días» usando el historial.
- Detección de apps de escritorio huérfanas (`.desktop` que apuntan a nada).
- Limpiar cachés de APT y miniaturas desde la propia app.

## Desarrollo

```bash
python3 tests/test_core.py            # pruebas del núcleo (sin interfaz)
python3 -m purgatio list --limit 20   # ver lo que detecta en tu equipo
./bin/purgatio --screenshot /tmp/purgatio.png   # captura la ventana a PNG
./bin/purgatio --view cleanup --screenshot /tmp/restos.png
```

`--screenshot` renderiza la ventana con GSK, así que funciona incluso en Wayland
sin depender de herramientas de captura del escritorio.

## Licencia

MIT.
