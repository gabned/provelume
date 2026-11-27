import sys

if sys.argv[1:] == ["--internal-ai-worker"]:
    from provelume.ai_windows_worker import main
elif sys.argv[1:2] == ["--internal-icalendar-worker"]:
    from provelume.icalendar_worker import main
else:
    from provelume.desktop import main

raise SystemExit(main())
