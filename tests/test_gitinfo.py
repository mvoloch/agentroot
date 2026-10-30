from agentroot import gitinfo

from conftest import TOKEN, make_repo, make_worktree


def test_credentials_never_survive():
    url = f"http://alice:{TOKEN}@10.0.0.5:3300/alice/dashboard.git"
    clean = gitinfo.strip_credentials(url)
    assert TOKEN not in clean and "alice:" not in clean
    assert clean == "http://10.0.0.5:3300/alice/dashboard.git"


def test_same_repo_same_key_across_url_styles():
    keys = {
        gitinfo.remote_key("https://github.com/Acme/Repo.git"),
        gitinfo.remote_key(f"https://user:{TOKEN}@github.com/acme/repo"),
        gitinfo.remote_key("git@github.com:acme/repo.git"),
        gitinfo.remote_key("ssh://git@github.com/acme/repo.git"),
    }
    assert keys == {"github.com/acme/repo"}


def test_find_clone_and_worktree_from_disk(tmp_path):
    main = make_repo(tmp_path / "proj", f"https://u:{TOKEN}@github.com/acme/proj.git")
    wt = make_worktree(main, tmp_path / "elsewhere" / "proj-wt", "proj-wt")
    (main / "src" / "deep").mkdir(parents=True)

    c = gitinfo.find(str(main / "src" / "deep"))
    assert c.kind == "clone" and c.root == str(main)
    assert TOKEN not in c.remote and c.remote_key == "github.com/acme/proj"

    w = gitinfo.find(str(wt))
    assert w.kind == "worktree" and w.root == str(wt)
    assert w.main_root == str(main) and w.remote_key == "github.com/acme/proj"


def test_not_a_repo(tmp_path):
    assert gitinfo.find(str(tmp_path), stop_at=str(tmp_path)) is None
