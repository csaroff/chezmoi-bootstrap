"""Executable scenarios; no network, package installs, real keys, or credentials."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"


class BootstrapScenarios(unittest.TestCase):
    def run_shell(self, scenario, expected=0):
        with tempfile.TemporaryDirectory(prefix="bootstrap-test-") as home:
            env = dict(os.environ, HOME=home, GH_TOKEN="", GITHUB_TOKEN="")
            result = subprocess.run(
                ["bash", "-c", 'source "$1"\nREPO=git@github.com:alice/config.git\nREPO_SLUG=alice/config\n' + scenario, "test", str(INSTALLER)],
                env=env, text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            return result.stdout

    def test_new_machine_uses_device_login_then_ssh_and_reviews_before_apply(self):
        # A user with no other computers can authorize in a browser and end with
        # a writable SSH checkout. Existing laptop private keys are not required.
        output = self.run_shell(r'''
confirm() { return 0; }
source_dir="$HOME/source"
mkdir -p "$source_dir" "$HOME/.ssh"
printf 'test-private-key' > "$KEY"
printf 'ssh-ed25519 TESTKEY machine\n' > "$KEY.pub"
gh() {
  printf 'gh %s\n' "$*" >> "$HOME/events"
  case "$*" in
    'auth status '*) return 1 ;;
    'api --hostname github.com user --jq .login') echo csaroff ;;
    'api --hostname github.com user/keys '*) echo 'ssh-ed25519 DIFFERENT' ;;
  esac
}
git() { printf 'git %s\n' "$*" >> "$HOME/events"; }
chezmoi() {
  printf 'chezmoi %s\n' "$*" >> "$HOME/events"
  [[ $1 != source-path ]] || echo "$source_dir"
}
github_login
configure_key
configure_dotfiles
[[ -z ${GIT_SSH_COMMAND:-} ]]
[[ $(<"$KEY") == test-private-key ]]
while IFS= read -r line; do printf '%s\n' "$line"; done < "$HOME/events"
''')
        self.assertIn("auth login --hostname github.com --git-protocol https --web", output)
        self.assertIn("config set git_protocol ssh --host github.com", output)
        self.assertIn("ssh-key add", output)
        self.assertIn("core.sshCommand ssh -i", output)
        self.assertIn("remote set-url origin git@github.com:alice/config.git", output)
        self.assertLess(output.index("chezmoi diff"), output.index("chezmoi apply"))

    def test_ubuntu_packaged_gh_can_login_without_unsupported_skip_flag(self):
        # Ubuntu 24.04 ships gh 2.45. A fresh-machine install must reach browser
        # authorization without requiring a newer CLI or letting gh choose keys.
        output = self.run_shell(r'''
confirm() { return 0; }
gh() {
  case "$*" in
    'auth status '*) return 1 ;;
    'auth login '*)
      for arg in "$@"; do
        if [[ $arg == --skip-ssh-key ]]; then
          echo 'unknown flag: --skip-ssh-key' >&2
          return 1
        fi
      done
      [[ " $* " == *' --git-protocol https '* ]] || return 98
      echo LOGIN_OK
      ;;
    'config set git_protocol ssh --host github.com') echo SSH_DEFAULT ;;
    'api --hostname github.com user --jq .login') echo alice ;;
    'api --hostname github.com user/keys '*) return 0 ;;
    *) return 99 ;;
  esac
}
github_login
''')
        self.assertIn('LOGIN_OK', output)
        self.assertIn('SSH_DEFAULT', output)

    def test_review_summarizes_before_user_requests_diff_and_applies(self):
        # First-run setup can contain thousands of lines. The user should see
        # scope and executable scripts before choosing whether to inspect details.
        output = self.run_shell(r'''
chezmoi() {
  case "$1" in
    status) printf ' A .gitconfig\n M .config/agent/AGENTS.md\n R setup-tools.sh\n' ;;
    diff) echo FULL_DIFF ;;
    apply) echo APPLIED ;;
    *) return 99 ;;
  esac
}
choices=0
read_review_choice() {
  choices=$((choices+1))
  case $choices in 1) REVIEW_CHOICE=1;; *) REVIEW_CHOICE=3;; esac
}
review_dotfiles
''')
        self.assertIn('2 file changes', output)
        self.assertIn('1 setup scripts', output)
        self.assertIn('setup-tools.sh', output)
        self.assertLess(output.index('2 file changes'), output.index('FULL_DIFF'))
        self.assertLess(output.index('FULL_DIFF'), output.index('APPLIED'))

    def test_review_cancel_does_not_render_diff_or_apply(self):
        self.run_shell(r'''
chezmoi() {
  [[ $1 == status ]] || { echo 'Unexpected diff/apply'; return 99; }
  printf ' A .gitconfig\n'
}
read_review_choice() { REVIEW_CHOICE=4; }
review_dotfiles
''')

    def test_public_one_liner_invokes_main_without_a_script_filename(self):
        # The documented curl -> bash -c entry point must run, not require a file
        # on disk. Substitute only main's body to avoid changing this computer.
        script = INSTALLER.read_text()
        start = script.index('main() {')
        end = script.index('\n}\n', start) + 3
        script = script[:start] + 'main() { echo BOOTSTRAP_STARTED; }\n' + script[end:]
        result = subprocess.run(['bash', '-c', script], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('BOOTSTRAP_STARTED', result.stdout)

    def test_standard_key_is_reused_without_prompt_or_regeneration(self):
        # Bootstrap should use this machine's existing identity, not introduce
        # another key or ask the user to make the same choice on every run.
        self.run_shell(r'''
[[ $KEY == "$HOME/.ssh/id_ed25519" ]]
mkdir -p "$HOME/.ssh"
printf private > "$KEY"
printf 'ssh-ed25519 TESTKEY\n' > "$KEY.pub"
confirm() { echo 'Unexpected reuse prompt'; exit 99; }
ssh-keygen() { echo 'Unexpected key generation'; exit 99; }
gh() { echo 'ssh-ed25519 TESTKEY'; }
git() { :; }
configure_key
[[ $(<"$KEY") == private ]]
''')

    def test_repository_is_selected_by_user_not_installer_author(self):
        # A different user's private repo must work without editing the installer.
        self.run_shell(r'''
set_repo alice/config
[[ $REPO == git@github.com:alice/config.git ]]
set_repo git@github.com:team/config.git
[[ $REPO == git@github.com:team/config.git ]]
set_repo https://github.com/alice/config.git
[[ $REPO == git@github.com:alice/config.git ]]
''')

    def test_invalid_repository_is_rejected(self):
        for value in ('--upload-pack=bad', 'alice/repo/extra', 'https://elsewhere.test/a/b', 'a/..'):
            with self.subTest(value=value):
                self.run_shell('set_repo ' + repr(value), expected=1)

    def test_missing_linux_tools_install_before_chezmoi(self):
        output = self.run_shell(r'''
confirm() { return 0; }
command() {
  if [[ $1 == -v ]]; then
    case "$2" in apt-get) return 0;; *) return 1;; esac
  fi
  builtin command "$@"
}
uname() { echo Linux; }
sudo() { printf 'sudo %s\n' "$*"; }
curl() { printf 'exit 0\n' > "${@: -1}"; }
install_tools
[[ $PATH == "$HOME/.local/bin:"* ]]
''')
        self.assertIn("sudo apt-get install -y git gh curl", output)

    def test_key_upload_retries_after_scope_authorization(self):
        output = self.run_shell(r'''
mkdir -p "$HOME/.ssh"
printf private > "$KEY"
printf 'ssh-ed25519 TESTKEY\n' > "$KEY.pub"
gh() {
  case "$*" in
    'api '*) echo 'ssh-ed25519 OTHER' ;;
    'ssh-key add '*) [[ -e "$HOME/refreshed" ]] ;;
    'auth refresh '*) touch "$HOME/refreshed" ;;
    *) return 99 ;;
  esac
}
git() { :; }
configure_key
test -e "$HOME/refreshed"
''')
        self.assertIn("retry once", output)

    def test_registered_key_is_reused_without_upload(self):
        self.run_shell(r'''
mkdir -p "$HOME/.ssh"
printf 'private-key' > "$KEY"
printf 'ssh-ed25519 TESTKEY machine\n' > "$KEY.pub"
gh() {
  [[ $1 == api ]] || { echo 'Unexpected upload'; return 99; }
  printf 'ssh-ed25519 TESTKEY\n'
}
git() { :; }
configure_key
[[ $(<"$KEY") == private-key ]]
''')

    def test_private_key_without_public_key_is_never_overwritten(self):
        output = self.run_shell(r'''
mkdir -p "$HOME/.ssh"
printf 'private-key' > "$KEY"
ssh-keygen() { return 1; }
configure_key
''', expected=1)
        self.assertIn("private key is unchanged", output)

    def test_missing_public_key_is_recovered_from_existing_private_key(self):
        self.run_shell(r'''
mkdir -p "$HOME/.ssh"
printf private > "$KEY"
ssh-keygen() { [[ $1 == -y ]] || exit 99; echo 'ssh-ed25519 TESTKEY'; }
gh() { echo 'ssh-ed25519 TESTKEY'; }
git() { :; }
configure_key
[[ $(<"$KEY") == private ]]
[[ $(<"$KEY.pub") == 'ssh-ed25519 TESTKEY' ]]
''')

    def test_existing_dirty_dotfiles_stop_before_init_or_apply(self):
        output = self.run_shell(r'''
mkdir -p "$HOME/source/.git"
chezmoi() { [[ $1 == source-path ]] || return 99; echo "$HOME/source"; }
git() {
  case "$*" in
    *'remote get-url origin') echo "$REPO" ;;
    *'status --porcelain') echo ' M dot_zshrc' ;;
    *) return 99 ;;
  esac
}
configure_dotfiles
''', expected=1)
        self.assertIn("local changes", output)

    def test_unrelated_existing_source_is_not_repointed(self):
        self.run_shell(r'''
mkdir -p "$HOME/source/.git"
chezmoi() { [[ $1 == source-path ]] || return 99; echo "$HOME/source"; }
git() { [[ "$*" == *'remote get-url origin' ]] || return 99; echo git@example.com:someone/dotfiles.git; }
configure_dotfiles
''', expected=1)

    def test_declining_apply_keeps_checkout_without_running_scripts(self):
        output = self.run_shell(r'''
DOTFILES_SSH='ssh -i test-key'
confirm() { return 1; }
git() { :; }
chezmoi() {
  case "$1" in
    source-path) echo "$HOME/source" ;;
    apply) echo 'Unexpected apply'; return 99 ;;
  esac
}
configure_dotfiles
''')
        self.assertIn("Initialized without applying", output)

    def test_environment_token_does_not_silently_select_account(self):
        self.run_shell(r'''
GH_TOKEN=not-a-real-token
gh() { echo 'Unexpected authentication call'; return 99; }
github_login
''', expected=1)

    def test_failed_github_login_stops_without_attempting_key_setup(self):
        self.run_shell(r'''
gh() { return 42; }
github_login
configure_key() { echo 'Should never run'; }
''', expected=42)

    def test_existing_login_missing_key_scope_requests_only_needed_scope(self):
        output = self.run_shell(r'''
confirm() { return 0; }
gh() {
  case "$*" in
    'auth status '*) return 0 ;;
    'api --hostname github.com user --jq .login') echo csaroff ;;
    'api --hostname github.com user/keys '*) return 1 ;;
    'auth refresh '*) printf '%s\n' "$*" ;;
    *) return 99 ;;
  esac
}
github_login
''')
        self.assertIn("auth refresh --hostname github.com --scopes admin:public_key", output)


if __name__ == "__main__":
    unittest.main()
