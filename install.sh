#!/usr/bin/env bash
# Public entry point. Secrets and machine configuration never belong here.
set -euo pipefail

REPO=
REPO_SLUG=
KEY="$HOME/.ssh/id_ed25519"

say() { printf '\n%s\n' "$*"; }
confirm() {
  local answer
  printf '%s [y/N] ' "$*" >/dev/tty
  IFS= read -r answer </dev/tty
  [[ "$answer" == y || "$answer" == Y || "$answer" == yes ]]
}

set_repo() {
  local slug=$1
  slug=${slug#https://github.com/}
  slug=${slug#git@github.com:}
  slug=${slug%.git}
  if [[ ! $slug =~ ^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+$ || ${slug#*/} == . || ${slug#*/} == .. ]]; then
    say 'Enter a GitHub OWNER/REPO, HTTPS URL, or git@github.com SSH URL.'
    return 1
  fi
  REPO_SLUG=$slug
  REPO="git@github.com:${slug}.git"
}

choose_repo() {
  local answer
  while true; do
    printf 'Dotfiles repository (OWNER/REPO): ' >/dev/tty
    IFS= read -r answer </dev/tty
    if set_repo "$answer"; then break; fi
  done
}

install_tools() {
  local missing=() tool os
  for tool in git gh ssh-keygen curl; do
    command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
  done
  if ((${#missing[@]})); then
    say "Missing prerequisites: ${missing[*]}"
    confirm 'Install prerequisites using the system package manager?' || return 1
    os=$(uname -s)
    case "$os" in
      Darwin)
        if ! command -v brew >/dev/null 2>&1; then
          say 'Installing Homebrew using its official installer (may request sudo).'
          local installer
          installer=$(mktemp)
          curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o "$installer"
          /bin/bash "$installer"
          rm -f "$installer"
          if [[ -x /opt/homebrew/bin/brew ]]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
          else
            eval "$(/usr/local/bin/brew shellenv)"
          fi
        fi
        brew install git gh curl
        ;;
      Linux)
        if command -v apt-get >/dev/null 2>&1; then
          sudo apt-get update
          sudo apt-get install -y git gh curl ca-certificates openssh-client
        elif command -v dnf >/dev/null 2>&1; then
          sudo dnf install -y git gh curl ca-certificates openssh-clients
        else
          say 'Unsupported Linux package manager. Supported: apt-get or dnf.'
          return 1
        fi
        ;;
      *) say "Unsupported OS: $os"; return 1 ;;
    esac
  fi
  if ! command -v chezmoi >/dev/null 2>&1; then
    local installer
    installer=$(mktemp)
    curl -fsSL https://get.chezmoi.io -o "$installer"
    sh "$installer" -b "$HOME/.local/bin"
    rm -f "$installer"
  fi
  export PATH="$HOME/.local/bin:$PATH"
}

github_login() {
  # Ambient tokens can mask a missing persistent login and select the wrong account.
  if [[ -n ${GH_TOKEN:-} || -n ${GITHUB_TOKEN:-} ]]; then
    say 'Unset GH_TOKEN/GITHUB_TOKEN before running interactive bootstrap.'
    return 1
  fi
  if ! gh auth status --hostname github.com >/dev/null 2>&1; then
    say 'Authorize GitHub in your browser. On a server, open the displayed URL on another device.'
    say 'GitHub CLI authorization is account-wide, not limited to the dotfiles repository.'
    say 'Without an OS keychain, gh may store its token in a plaintext file.'
    # HTTPS login avoids gh's automatic SSH-key setup on older CLIs that lack
    # --skip-ssh-key. Restore the SSH default; key registration happens below.
    gh auth login --hostname github.com --git-protocol https --web --scopes admin:public_key
    gh config set git_protocol ssh --host github.com
  fi
  local account
  account=$(gh api --hostname github.com user --jq .login)
  confirm "Continue using GitHub account '$account' on this machine?" || return 1
  if ! gh api --hostname github.com user/keys --paginate --jq '.[].key' >/dev/null 2>&1; then
    gh auth refresh --hostname github.com --scopes admin:public_key
  fi
}

configure_key() {
  install -d -m 700 "$HOME/.ssh"
  if [[ -e "$KEY" && ! -e "$KEY.pub" ]]; then
    say "Recovering the missing public key from $KEY (private key is unchanged)."
    local recovered
    recovered=$(mktemp "$HOME/.ssh/public-key.XXXXXX")
    if ! ssh-keygen -y -f "$KEY" > "$recovered"; then
      rm -f "$recovered"
      return 1
    fi
    mv "$recovered" "$KEY.pub"
  fi
  if [[ ! -e "$KEY" ]]; then
    say 'Creating ~/.ssh/id_ed25519. Choose a passphrase when prompted (recommended).'
    [[ ! -e "$KEY.pub" ]] || { say "Orphan public key exists: $KEY.pub"; return 1; }
    ssh-keygen -t ed25519 -f "$KEY" -C "chezmoi@$(hostname)" </dev/tty
  fi
  local public_key registered
  public_key=$(awk '{print $1 " " $2}' "$KEY.pub")
  registered=$(gh api --hostname github.com user/keys --paginate --jq '.[].key')
  if ! grep -Fxq "$public_key" <<<"$registered"; then
    if ! GH_HOST=github.com gh ssh-key add "$KEY.pub" --type authentication --title "chezmoi@$(hostname)"; then
      # Existing logins may list keys but lack permission to register one.
      say 'Key registration failed. Authorize SSH-key management, then retry once.'
      gh auth refresh --hostname github.com --scopes admin:public_key
      GH_HOST=github.com gh ssh-key add "$KEY.pub" --type authentication --title "chezmoi@$(hostname)"
    fi
  fi
  # Repository-local configuration avoids rewriting the user's SSH config or other repos.
  printf -v DOTFILES_SSH 'ssh -i %q -o IdentitiesOnly=yes' "$KEY"
  export GIT_SSH_COMMAND="$DOTFILES_SSH"
  say 'Checking SSH repository access. Verify the GitHub host fingerprint if SSH prompts.'
  git ls-remote "$REPO" HEAD >/dev/null
}

configure_dotfiles() {
  local source origin
  source=$(chezmoi source-path)
  if [[ -d "$source/.git" ]]; then
    origin=$(git -C "$source" remote get-url origin)
    case "$origin" in
      "$REPO"|"https://github.com/$REPO_SLUG.git"|"https://github.com/$REPO_SLUG") ;;
      *) say "Existing chezmoi source uses unexpected origin: $origin. Stopping without changing it."; return 1 ;;
    esac
    if [[ -n $(git -C "$source" status --porcelain) ]]; then
      say 'Chezmoi source has local changes. Commit or stash them yourself, then rerun.'
      return 1
    fi
    # Never silently pull, reset, or overwrite an existing source checkout.
  fi
  chezmoi init "$REPO"
  source=$(chezmoi source-path)
  git -C "$source" config core.sshCommand "$DOTFILES_SSH"
  git -C "$source" remote set-url origin "$REPO"
  unset GIT_SSH_COMMAND
  say 'Review configuration changes below. Apply also executes scripts in your dotfiles repository.'
  chezmoi diff
  if confirm 'Apply these dotfiles and their setup scripts?'; then
    chezmoi apply
  else
    say 'Initialized without applying. Later: chezmoi diff, then chezmoi apply.'
  fi
  say "Ready: SSH dotfiles checkout at $source"
  say 'Provider/work credentials are not imported by this installer.'
  say 'Git author identity and other setup prompts depend on your dotfiles repository.'
}

main() {
  if [[ ${EUID:-$(id -u)} == 0 ]]; then
    say 'Run as your everyday user, not root. Package installation uses sudo when needed.'
    return 1
  fi
  [[ -r /dev/tty && -w /dev/tty ]] || { say 'An interactive terminal is required.'; return 1; }
  export GIT_PAGER=cat PAGER=cat
  say 'Bootstrap: prerequisites → GitHub login → machine SSH key → chezmoi review/apply.'
  install_tools
  github_login
  choose_repo
  configure_key
  configure_dotfiles
}

# bash -c (the one-line installer) has no BASH_SOURCE entry.
if [[ -z ${BASH_SOURCE[0]:-} || ${BASH_SOURCE[0]} == "$0" ]]; then main "$@"; fi
