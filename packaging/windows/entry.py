import sys

if sys.argv[1:] == ["--internal-ai-worker"]:
    from provelume.ai_windows_worker import main
else:
    from provelume.desktop import main

raise SystemExit(main())
