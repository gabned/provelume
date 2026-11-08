import sys

if sys.argv[1:] == ["--internal-ai-worker"]:
    from provelume.ai_windows_worker import main
elif sys.argv[1:2] == ["--internal-icalendar-worker"]:
    from provelume.icalendar_worker import main
elif sys.argv[1:2] == ["--internal-productivity-http-worker"]:
    from provelume.productivity_http import main
elif sys.argv[1:2] == ["--internal-github-http-worker"]:
    from provelume.mirror_github_http import main
elif sys.argv[1:2] == ["--internal-github-git-credential"]:
    from provelume.mirror_github_helper import main
elif sys.argv[1:2] == ["--internal-gitlab-http-worker"]:
    from provelume.mirror_gitlab_http import main
elif sys.argv[1:2] == ["--internal-gitlab-git-credential"]:
    from provelume.mirror_gitlab_helper import main
elif sys.argv[1:2] == ["--internal-gitea-http-worker"]:
    from provelume.mirror_gitea_http import main
elif sys.argv[1:2] == ["--internal-gitea-git-credential"]:
    from provelume.mirror_gitea_helper import main
elif sys.argv[1:2] == ["--internal-rsync-agent-worker"]:
    from provelume.mirror_ssh_agent_worker import main
else:
    from provelume.desktop import main

raise SystemExit(main())
