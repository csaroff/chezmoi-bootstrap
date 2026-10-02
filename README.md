# Developer bootstrap

One command on a new machine: install prerequisites, authorize GitHub, register a
machine-specific SSH key, and initialize your private chezmoi dotfiles over SSH.
No existing laptop, private key, or checkout required.

## Run

As your normal user (not root), with an interactive terminal and `curl` installed:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/csaroff/dev-bootstrap/main/install.sh)"
```

This executes code from this repository. Review `install.sh` first if desired;
replace `main` with a reviewed commit SHA to pin the installer version. You need
network access, permission to install missing packages, and access to your GitHub
account/MFA. On a minimal machine without curl, install curl first.

Supported: macOS with Homebrew (installed if missing), Debian/Ubuntu with apt,
and Fedora-family distributions whose dnf repositories provide `gh`.
Unsupported package repositories fail rather than silently adding new ones.

## What you do

1. Approve prerequisite installation if needed (may require sudo).
2. Authorize GitHub using the displayed browser/device flow and confirm the account.
3. Enter your dotfiles repository as `OWNER/REPO` (GitHub HTTPS/SSH URLs also work).
4. If `~/.ssh/id_ed25519` exists, it is reused automatically without a reuse prompt.
   Otherwise choose a passphrase for the new key. Unattended pushes with an
   encrypted key require unlocking it in an SSH agent.
5. Answer any initialization prompts supplied by your dotfiles repository.
6. Review `chezmoi diff` and approve applying the configuration and its scripts.

## What it changes

- Installs missing Git/GitHub CLI/curl/SSH tools and chezmoi (`~/.local/bin`).
- Uses GitHub CLI authentication; requests SSH-key management permission when needed.
- Reuses `~/.ssh/id_ed25519` or creates it only if missing; never overwrites it.
  If its public key is missing, derives it from the existing private key
  (may prompt for the key's passphrase).
- Registers the public key under `chezmoi@HOSTNAME` on GitHub if not already registered.
- Initializes your chosen GitHub repository with chezmoi, using an SSH remote.
- Sets **repository-local** `core.sshCommand` to select this key for future
  chezmoi pull/push operations, including when an older bootstrap selected a
  different key. Other repositories and your SSH config are untouched.
- Converts an existing clean HTTPS checkout of that same repository to SSH.
- Refuses dirty or unrelated existing chezmoi source checkouts. Does not pull,
  reset, or overwrite source changes on rerun. Declining apply preserves the checkout.

The default GitHub host-key verification remains enabled. Compare a first-connect
fingerprint with [GitHub's published fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints).

## Security and scope

GitHub CLI OAuth and account SSH keys are **not scoped only to dotfiles**. The key
can access repositories your account permits; organization policies may require
additional SSO authorization. Register it only on a trusted machine.
Without a functioning OS credential store, `gh` may retain its OAuth token in a
plaintext configuration file. Run `gh auth status --hostname github.com` to check.
The installer refuses ambient `GH_TOKEN`/`GITHUB_TOKEN` variables to avoid silently
using a transient credential or the wrong account.

This first version does **not** import model-provider, Bitwarden, work, Artifactory,
ICR, or Pi-login credentials. Those need separately designed, opt-in credential
sources and work/personal segregation. Your dotfiles' existing apply scripts still
run when you approve apply; inspect them as well as the diff.

This installs dotfiles; it does not promise to install every application referenced
by them. Never put secrets in this public repository.

When retiring a machine, remove its key in [GitHub SSH settings](https://github.com/settings/keys)
and remove/revoke any GitHub CLI credential as appropriate. Deleting a VM is not revocation.

## Verification

```bash
bash -n install.sh
shellcheck install.sh
python3 -m unittest discover -s tests -v
```

Tests simulate GitHub/device authorization and the SSH/chezmoi lifecycle without
network access or real secrets. They do not constitute a real browser-login or
fresh-OS installation test; those require an interactive trial.
