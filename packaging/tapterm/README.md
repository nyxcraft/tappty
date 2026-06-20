# tapterm

`tapterm` is the command-line program of the **[tappty](https://pypi.org/project/tappty/)**
instrumented-terminal toolkit — host a program on a pseudo-terminal, then observe, control,
and render it in a terminal (CUI), a green-phosphor window (GUI), or a browser tab.

This package is a thin **alias**: it ships no code of its own and simply depends on `tappty`,
which provides the `tapterm` command. So these are equivalent:

```sh
pip install tapterm     # convenience alias -> pulls in tappty
pip install tappty      # the actual toolkit (library + the tapterm command)
```

Either way you get the `tapterm` command and `import tappty`. The library, the optional
extras (`sdl` / `gl` / `web` / `video` / `ansi` / `win`), the documentation, and the source all
live under **tappty**:

- Docs: <https://nyxbitco.github.io/tappty/>
- Source & issues: <https://github.com/nyxbitco/tappty>
