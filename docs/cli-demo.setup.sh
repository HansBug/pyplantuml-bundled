# Sourced by VHS before any visible step.  Sets a coloured prompt,
# defines fake pip output (so the GIF doesn't need network access)
# and a cat() override that adds light ANSI highlighting for .puml
# keywords / arrows.  Real plantuml binary calls go through unchanged.

unset PROMPT_COMMAND
export PS1=$'\033[1;32mdemo\033[0;36m$\033[0m '
export TERM=xterm-256color
export PYTHONUNBUFFERED=1
stty rows 28 cols 110 2>/dev/null || true

# Coloured fake pip — mirrors what real pip prints to a TTY.  Same
# version + platform tag as the actual published wheel so the demo
# stays truthful to the released artifact.
pip() {
    if [[ "${1:-}" == "install" ]]; then
        printf '\033[36m%s\033[0m\n'  'Collecting pyplantuml-bundled'
        sleep 0.4
        printf '\033[36m  %s\033[0m\n' 'Downloading pyplantuml_bundled-1.2024.7.1-py3-none-manylinux_2_17_x86_64.whl (58 MB)'
        sleep 0.6
        printf '\033[36m%s\033[0m\n'  'Installing collected packages: pyplantuml-bundled'
        sleep 0.3
        printf '\033[1;32m%s\033[0m\n' 'Successfully installed pyplantuml-bundled-1.2024.7.1'
    else
        command pip "$@"
    fi
}

# Light syntax-highlighting for .puml files.  No `bat` / external
# dep; just sed-driven ANSI on the keywords + arrows + the success
# tick.  Falls through to real `cat` for any other file.
cat() {
    if [[ $# -ge 1 && "$1" == *.puml ]]; then
        command sed -E \
            -e 's/(@startuml|@enduml)/\x1b[1;35m\1\x1b[0m/g' \
            -e 's/^(title) /\x1b[1;33m\1\x1b[0m /' \
            -e 's/( -> | --> )/\x1b[1;36m\1\x1b[0m/g' \
            -e 's/(\xe2\x9c\x93)/\x1b[1;32m\1\x1b[0m/g' \
            "$@"
    else
        command cat "$@"
    fi
}

# Suppress the benign "Fontconfig warning ... reset-dirs" emitted by
# the bundled libfontconfig when it sees newer system config syntax.
# Rendering is unaffected; the warning just adds noise to the GIF.
plantuml() { command plantuml "$@" 2>/dev/null; }

cd /tmp/cli-demo
