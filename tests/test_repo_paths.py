from orchestrator_agent.repo_intake import find_repo


def test_parent_relative_path_keeps_leading_dots(tmp_path, monkeypatch):
    workspace = tmp_path / "dv_agent"
    repo = tmp_path / "baseline_repos" / "design"
    workspace.mkdir()
    repo.mkdir(parents=True)
    monkeypatch.chdir(workspace)
    assert find_repo("Use ../baseline_repos/design", workspace) == repo


def test_quoted_path_with_spaces(tmp_path):
    workspace = tmp_path / "dv_agent"
    repo = tmp_path / "design sources"
    workspace.mkdir()
    repo.mkdir()
    assert find_repo(f'Use "{repo}"', workspace) == repo


def test_absolute_path(tmp_path):
    workspace = tmp_path / "dv_agent"
    repo = tmp_path / "design"
    workspace.mkdir()
    repo.mkdir()
    assert find_repo(str(repo), workspace) == repo
