# mempalace-setup

**Português** | [English](README.en.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)

Setup **global da máquina** do [MemPalace](https://github.com/MemPalace/mempalace) para o Claude Code: um script que configura os hooks que salvam automaticamente o histórico de conversas e uma nota mínima de recall no `~/.claude/CLAUDE.md` global. Roda uma vez por máquina — não pertence a nenhum projeto ou repositório específico. Funciona em Windows com Smart App Control ligado.

## Setup

```
python scripts/setup_mempalace.py --dry-run   # ver o que mudaria (mostra um diff, não grava nada)
python scripts/setup_mempalace.py             # aplicar
```

Depois de aplicar, reinicie o Claude Code — os hooks só são carregados no início da sessão.

O script:
- Procura um comando `mempalace` que **rode de verdade**, executando `--version`: primeiro `<python do venv da ferramenta> -m mempalace`, depois o lançador `mempalace` do PATH. Só instala (`uv` → `pipx` → `pip`) se nenhum funcionar.
- Configura hooks globais do Claude Code (`Stop`/`SessionEnd`/`PreCompact`, timeout 30) com o comando que funcionou + `hook run` — sem scripts `.sh`, então funciona igual em Windows/Linux/macOS. Hooks do MemPalace já existentes são atualizados, não duplicados. Faz backup do `settings.json` antes.
- Garante uma nota mínima de recall no `~/.claude/CLAUDE.md` global. Se já existir uma nota sobre MemPalace sem o marcador (escrita à mão, em qualquer idioma), ela é envolvida com o marcador em vez de duplicada.
- Imprime onde fica o palace.
- Sai com código 1 se alguma etapa falhar (ex.: `settings.json` com JSON inválido — ele não mexe no arquivo).

O que ele **não** faz automaticamente (decisão sua, quando quiser):
```
mempalace mine ~/.claude/projects/ --mode convos   # minerar conversas passadas
mempalace mine <pasta-do-projeto>                    # minerar código/docs de um projeto
```

Também não registra o bloco `mempalace rules` (protocolo completo de coordenação multi-agente, MCP com 45 ferramentas) — isso é escopo bem maior do que "memória entre sessões". Se você quiser isso, é uma decisão separada (`mempalace rules --help`).

## Onde fica o palace (e como conferir)

- **Palace (os dados):** `~/.config/mempalace/palace` — no Windows, `%USERPROFILE%\.config\mempalace\palace`. O caminho vem de `palace_path` em `~/.config/mempalace/config.json`.
- **`~/.mempalace`:** só estado dos hooks e locks (`hook_state/`, `locks/`). Não é um segundo palace.

O palace é **um só por máquina**, compartilhado por todos os seus projetos: uma busca feita a partir de um projeto pode trazer conversas de outro. Se precisar de isolamento real, aponte `palace_path` para caminhos diferentes ou use perfis/máquinas separados.

Para conferir (use o python do venv da ferramenta — ver seção Windows abaixo):
```
<python> -m mempalace status    # quantos drawers, por wing/room
<python> -c "from mempalace.config import MempalaceConfig; print(MempalaceConfig().palace_path)"
```
O `setup_mempalace.py` também imprime o caminho real no final.

## Windows: Smart App Control / Application Control

Os lançadores `.exe` que o `uv`/`pipx` criam (ex.: `~/.local/bin/mempalace.exe`) não são assinados, e o Smart App Control (ou outra política de Application Control) pode bloqueá-los — às vezes de forma intermitente. O `python.exe` do venv da ferramenta é assinado, então o caminho confiável é chamar o módulo:

```
C:/Users/<você>/AppData/Roaming/uv/tools/mempalace/Scripts/python.exe -m mempalace status
```

O script já prefere essa forma e grava nos hooks com barras `/` (os hooks rodam no Git Bash). Use o mesmo prefixo no lugar de `mempalace` nos comandos deste README. Bloqueios aparecem no Visualizador de Eventos em *Microsoft-Windows-CodeIntegrity/Operational*.

## Usando junto com uma LLM Wiki

Combina bem com o [llm-wiki-template](https://github.com/pietrogconte/llm-wiki-template), mas as duas coisas são independentes: a wiki é um molde por projeto; este setup é por máquina.

| | LLM Wiki (`wiki/`) | MemPalace |
|---|---|---|
| O que guarda | Síntese **curada**: só o que o agente decidiu que valia a pena virar página | Histórico **verbatim** de tudo — cada conversa, sem filtro |
| Onde vive | Dentro do repositório da wiki, versionado no git | Fora de qualquer repo, num palace único por máquina (`~/.config/mempalace/palace`), **compartilhado entre todos os seus projetos** |
| Você lê direto? | Sim — é markdown, abre no Obsidian, é o produto final | Não — é uma busca (`mempalace search`), não um lugar pra navegar |
| Quando o agente usa | Sempre, pra responder sobre o que **já está** documentado na wiki (`wiki/index.md`) | Só quando falta contexto que não chegou a virar página ainda — ex.: "o que discutimos sobre X na semana passada?" |

Na prática: a wiki é a "versão final" que você cultiva; o MemPalace é uma rede de segurança que evita perder o que ainda não foi promovido a página.

## Créditos

- MemPalace: [MemPalace/mempalace](https://github.com/MemPalace/mempalace) (MIT).
- Este script foi montado com [Claude Code](https://claude.com/claude-code).

## Licença

MIT — veja [LICENSE](LICENSE).
