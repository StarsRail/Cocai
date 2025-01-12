# Directory for game modules

Put your Markdown-typed game modules here.

If your game module comes as one single file, as the default module _“Clean Up, Aisle Four!”_ does, you may choose to explicitly split the document into separate files, which may aid Cocai's retrival:

```shell
uv run --with mdsplit -m mdsplit "your-game-module.md" -l 3 -t -o "your-game-module/"
```

To use your own game module, set an environment variable `GAME_MODULE_PATH` to the path of the directory containing the module's files. It defaults to `game_modules/Clean-Up-Aisle-Four`.
