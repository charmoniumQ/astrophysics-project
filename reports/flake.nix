{
  description = "A simple Go package";

  # Nixpkgs / NixOS version to use.
  inputs.nixpkgs.url = "nixpkgs/nixos-21.11";

  inputs.flake-utils.url = "github:numtide/flake-utils";

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        # see https://github.com/NixOS/nixpkgs/blob/nixos-21.11/pkgs/tools/typesetting/tectonic/default.nix#L48
        tectonic = (
          pkgs.rustPlatform.buildRustPackage rec {
            pname = "tectonic";
            version = "0.8.0";

            src = pkgs.fetchFromGitHub {
              owner = "tectonic-typesetting";
              repo = "tectonic";
              rev = "c77ef784564b26114c129c3d49349911835eb822";
              fetchSubmodules = true;
              sha256 = "1x6pxzl2fxv0ldfdlgm5x2pcbkny8cf2b4gpk8yj8hhnn1ypim1w";
            };

            cargoSha256 = "0v5jc26icz83ssky85c8l92jcmglq9f2jbihfh4yqanpmwbpp5fl";

            nativeBuildInputs = [ pkgs.pkg-config pkgs.makeWrapper ];

            buildInputs = [ pkgs.fontconfig pkgs.harfbuzz pkgs.openssl pkgs.icu ];

            # Tectonic runs biber when it detects it needs to run it, see:
            # https://github.com/tectonic-typesetting/tectonic/releases/tag/tectonic%400.7.0
            postInstall = ''
    wrapProgram $out/bin/tectonic \
      --prefix PATH "${nixpkgs.lib.getBin pkgs.biber}/bin"
  '' + pkgs.lib.optionalString pkgs.stdenv.isLinux ''
    substituteInPlace dist/appimage/tectonic.desktop \
      --replace Exec=tectonic Exec=$out/bin/tectonic
    install -D dist/appimage/tectonic.desktop -t $out/share/applications/
    install -D dist/appimage/tectonic.svg -t $out/share/icons/hicolor/scalable/apps/
  '';

            doCheck = true;

            meta = with pkgs.lib; {
              description = "Modernized, complete, self-contained TeX/LaTeX engine, powered by XeTeX and TeXLive";
              homepage = "https://tectonic-typesetting.github.io/";
              changelog = "https://github.com/tectonic-typesetting/tectonic/blob/tectonic@${version}/CHANGELOG.md";
              license = with licenses; [ mit ];
              maintainers = [ maintainers.lluchs maintainers.doronbehar ];
            };
          }
        );
      in rec {
        devShell = pkgs.mkShell {
          # nativeBuildInputs is usually what you want -- tools you need to run
          nativeBuildInputs = [
            tectonic
            pkgs.biber
          ];
        };
      }
    );
}
