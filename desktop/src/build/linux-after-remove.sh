#!/bin/bash

# Delete the link to the binary
# update-alternatives --remove <name> <path>: 'path' must be the registered alternative binary,
# not the generic symlink — see https://man7.org/linux/man-pages/man1/update-alternatives.1.html
if type update-alternatives >/dev/null 2>&1; then
    update-alternatives --remove '${executable}' '/opt/${sanitizedProductName}/${executable}'
else
    rm -f '/usr/bin/${executable}'
fi

APPARMOR_PROFILE_DEST='/etc/apparmor.d/${executable}'

# Remove and unload apparmor profile.
if [ -f "$APPARMOR_PROFILE_DEST" ]; then
  # Unload the profile from the running kernel before deleting the file so the
  # policy is not left enforced until the next reboot.  Mirror the chroot guard
  # used in the after-install script — live AppArmor operations are not
  # meaningful inside a chroot.
  # https://wiki.debian.org/AppArmor/HowToUse
  if apparmor_status --enabled > /dev/null 2>&1; then
    if ! { [ -x '/usr/bin/ischroot' ] && /usr/bin/ischroot; } && hash apparmor_parser 2>/dev/null; then
      apparmor_parser --remove "$APPARMOR_PROFILE_DEST" || true
    fi
  fi
  rm -f "$APPARMOR_PROFILE_DEST"
fi

# Upgrade calls this script too. Only a real removal takes the desktop icon.
# dpkg postrm passes remove or purge. rpm %postun passes 0 on erase and 1 on
# upgrade, so 1 must leave the icon in place.
# The helper file is already gone, so its text is inlined below.
# BEGIN linux-desktop-shortcut.sh
#!/bin/bash
# Desktop launcher for the deb and rpm maintainer scripts.
#
# The package install runs as root, so $HOME is /root. The invoking account is SUDO_USER,
# PKEXEC_UID, or logname. A graphical installer that is just root falls back
# to ordinary user accounts. The first successful placement for an account
# writes a stamp; later upgrades refresh an icon that is still on the desktop
# and do not put back one the user deleted. Uninstall removes both.

happyclaw_as_user() {
  local user="$1"
  shift
  if command -v runuser >/dev/null 2>&1; then
    runuser -u "$user" -- "$@"
    return
  fi
  if command -v sudo >/dev/null 2>&1; then
    sudo -u "$user" -H -- "$@"
    return
  fi
  return 1
}

happyclaw_invoking_user() {
  local user="${SUDO_USER-}"
  if [ -z "$user" ] || [ "$user" = "root" ]; then
    if [ -n "${PKEXEC_UID-}" ]; then
      user="$(id -nu "$PKEXEC_UID" 2>/dev/null || true)"
    fi
  fi
  if [ -z "$user" ] || [ "$user" = "root" ]; then
    user="$(logname 2>/dev/null || true)"
  fi
  if [ -z "$user" ] || [ "$user" = "root" ]; then
    return 0
  fi
  printf '%s\n' "$user"
}

happyclaw_human_users() {
  getent passwd | awk -F: '$3+0 >= 1000 && $3+0 < 65534 { print $1 }'
}

happyclaw_install_targets() {
  local user=""
  user="$(happyclaw_invoking_user)"
  if [ -n "$user" ]; then
    printf '%s\n' "$user"
    return 0
  fi
  happyclaw_human_users
}

happyclaw_remove_targets() {
  happyclaw_invoking_user
  happyclaw_human_users
}

happyclaw_user_home() {
  getent passwd "$1" | awk -F: '{ print $6; exit }'
}

happyclaw_expand_home() {
  local home="$1"
  local path="$2"
  case "$path" in
    '$HOME'/*)
      printf '%s\n' "$home/${path#\$HOME/}"
      ;;
    '~'/*)
      printf '%s\n' "$home/${path#\~/}"
      ;;
    *)
      printf '%s\n' "$path"
      ;;
  esac
}

happyclaw_desktop_dir() {
  local user="$1"
  local home="$2"
  local dir="" raw=""
  if command -v xdg-user-dir >/dev/null 2>&1; then
    dir="$(happyclaw_as_user "$user" xdg-user-dir DESKTOP 2>/dev/null || true)"
    dir="$(happyclaw_expand_home "$home" "$dir")"
  fi
  if [ -z "$dir" ] || [ "$dir" = "$home" ]; then
    if [ -f "$home/.config/user-dirs.dirs" ]; then
      raw="$(sed -n 's/^XDG_DESKTOP_DIR=//p' "$home/.config/user-dirs.dirs" | head -n 1)"
      raw="${raw#\"}"
      raw="${raw%\"}"
      raw="${raw#\'}"
      raw="${raw%\'}"
      dir="$(happyclaw_expand_home "$home" "$raw")"
    fi
  fi
  if [ -n "$dir" ] && [ "$dir" != "$home" ] && [ -d "$dir" ]; then
    printf '%s\n' "$dir"
    return 0
  fi
  if [ -d "$home/Desktop" ]; then
    printf '%s\n' "$home/Desktop"
    return 0
  fi
  if [ -d "$home/桌面" ]; then
    printf '%s\n' "$home/桌面"
    return 0
  fi
  return 0
}

happyclaw_chown() {
  local user="$1"
  local path="$2"
  local group=""
  group="$(id -gn "$user" 2>/dev/null || true)"
  if [ -n "$group" ]; then
    chown "$user:$group" "$path" 2>/dev/null || true
    return 0
  fi
  chown "$user" "$path" 2>/dev/null || true
}

happyclaw_trust_launcher() {
  local user="$1"
  local link="$2"
  local uid=""
  command -v gio >/dev/null 2>&1 || return 0
  uid="$(id -u "$user" 2>/dev/null || true)"
  if [ -n "$uid" ] && [ -S "/run/user/$uid/bus" ]; then
    happyclaw_as_user "$user" env \
      DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" \
      XDG_RUNTIME_DIR="/run/user/$uid" \
      gio set "$link" metadata::trusted true >/dev/null 2>&1 || true
    return 0
  fi
  happyclaw_as_user "$user" gio set "$link" metadata::trusted true >/dev/null 2>&1 || true
}

happyclaw_install_launcher() {
  local entry="$1"
  local link="$2"
  local user="$3"
  local home="$4"
  local stamp_dir="$home/.local/share/happyclaw"
  local stamp="$stamp_dir/desktop-shortcut-created"
  if [ -f "$stamp" ] && [ ! -e "$link" ]; then
    return 0
  fi
  if [ -e "$link" ] && [ ! -L "$link" ] && [ ! -f "$link" ]; then
    return 0
  fi
  local next="$link.happyclaw-new"
  rm -f "$next" || return 0
  cp "$entry" "$next" || return 0
  chmod 755 "$next" || true
  if [ -L "$link" ] || [ -f "$link" ]; then
    rm -f "$link" || {
      rm -f "$next"
      return 0
    }
  fi
  mv -f "$next" "$link" || {
    rm -f "$next"
    return 0
  }
  happyclaw_chown "$user" "$link"
  happyclaw_trust_launcher "$user" "$link"
  if [ -f "$stamp" ]; then
    return 0
  fi
  mkdir -p "$stamp_dir" || return 0
  happyclaw_chown "$user" "$stamp_dir"
  : >"$stamp" || return 0
  chmod 644 "$stamp" || true
  happyclaw_chown "$user" "$stamp"
}

happyclaw_usable_home() {
  local home="$1"
  [ -n "$home" ] && [ -d "$home" ] || return 1
  case "$home" in
    / | /root | /nonexistent | /var/empty) return 1 ;;
  esac
  return 0
}

happyclaw_sync_desktop_shortcut() {
  local entry="$1"
  local filename="$2"
  local user="" home="" desk=""
  [ -f "$entry" ] || return 0
  case "$filename" in
    "" | */* | *\\*) return 0 ;;
  esac
  while IFS= read -r user; do
    [ -n "$user" ] || continue
    home="$(happyclaw_user_home "$user")"
    happyclaw_usable_home "$home" || continue
    desk="$(happyclaw_desktop_dir "$user" "$home")"
    [ -n "$desk" ] && [ -d "$desk" ] || continue
    case "$desk" in
      *$'\n'*) continue ;;
    esac
    happyclaw_install_launcher "$entry" "$desk/$filename" "$user" "$home" || true
  done <<EOF
$(happyclaw_install_targets)
EOF
}

happyclaw_remove_file() {
  local path="$1"
  if [ -L "$path" ] || [ -f "$path" ]; then
    rm -f "$path" || true
  fi
}

happyclaw_remove_desktop_shortcut() {
  local filename="$1"
  local user="" home="" desk=""
  case "$filename" in
    "" | */* | *\\*) return 0 ;;
  esac
  while IFS= read -r user; do
    [ -n "$user" ] || continue
    home="$(happyclaw_user_home "$user")"
    happyclaw_usable_home "$home" || continue
    desk="$(happyclaw_desktop_dir "$user" "$home")"
    if [ -n "$desk" ]; then
      happyclaw_remove_file "$desk/$filename"
    fi
    happyclaw_remove_file "$home/Desktop/$filename"
    happyclaw_remove_file "$home/桌面/$filename"
    happyclaw_remove_file "$home/.local/share/happyclaw/desktop-shortcut-created"
  done <<EOF
$(happyclaw_remove_targets)
EOF
}
# END linux-desktop-shortcut.sh

case "${1-}" in
  remove|purge|0)
    happyclaw_remove_desktop_shortcut '${executable}.desktop' || true
    ;;
esac
