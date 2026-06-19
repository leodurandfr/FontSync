# Formula Homebrew pour l'agent FontSync (canal CLI optionnel — cf. PLAN-PUBLICATION.md P5.1).
#
# Pour les power-users / serveurs headless qui ne veulent pas l'app Mac : installe
# `fontsync-agent` dans un virtualenv isolé (toutes les deps résolues comme des
# `resource`, pip-installées via `virtualenv_install_with_resources`). pyobjc est
# installé par son chemin supporté (pip), comme dans l'app — pas de freezer.
#
# Ce fichier est la source canonique ; il est miré dans le tap `leodurandfr/homebrew-tap`
# (cf. packaging/homebrew/README.md). Installation finale :
#   brew install leodurandfr/tap/fontsync-agent
#
# À CHAQUE RELEASE : pousser le tag `vX.Y.Z`, puis mettre à jour `url`/`version` et
# régénérer `sha256` (`brew fetch`) + les `resource` (`brew update-python-resources`).
class FontsyncAgent < Formula
  include Language::Python::Virtualenv

  desc "Agent de synchronisation de polices FontSync (macOS, launchd + SSE)"
  homepage "https://github.com/leodurandfr/FontSync"
  url "https://github.com/leodurandfr/FontSync/archive/refs/tags/v0.1.0.tar.gz"
  # Régénérer au moment du tag : `brew fetch --build-from-source ./Formula/fontsync-agent.rb`
  # ou `curl -sL <url> | shasum -a 256`. Placeholder tant que v0.1.0 n'est pas taggué.
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "AGPL-3.0-or-later"

  depends_on :macos
  depends_on "python@3.12"

  resource "anyio" do
    url "https://files.pythonhosted.org/packages/1c/b5/001890774a9552aff22502b8da382593109ce0c95314abaebbb116567545/anyio-4.14.0.tar.gz"
    sha256 "b47c1f9ccf73e67021df785332508f99379c68fa7d0684e8e3492cb1d4b23f89"
  end

  resource "certifi" do
    url "https://files.pythonhosted.org/packages/c9/c7/424b75da314c1045981bd9777432fad05a9e0c69daa4ed7e308bbaffe405/certifi-2026.6.17.tar.gz"
    sha256 "024c88eeec92ca068db80f02b8b07c9cef7b9fe261d1d535abfd5abd6f6af432"
  end

  resource "h11" do
    url "https://files.pythonhosted.org/packages/01/ee/02a2c011bdab74c6fb3c75474d40b3052059d95df7e73351460c8588d963/h11-0.16.0.tar.gz"
    sha256 "4e35b956cf45792e4caa5885e69fba00bdbc6ffafbfa020300e549b208ee5ff1"
  end

  resource "httpcore" do
    url "https://files.pythonhosted.org/packages/06/94/82699a10bca87a5556c9c59b5963f2d039dbd239f25bc2a63907a05a14cb/httpcore-1.0.9.tar.gz"
    sha256 "6e34463af53fd2ab5d807f399a9b45ea31c3dfa2276f15a2c3f00afff6e176e8"
  end

  resource "httpx" do
    url "https://files.pythonhosted.org/packages/b1/df/48c586a5fe32a0f01324ee087459e112ebb7224f646c0b5023f5e79e9956/httpx-0.28.1.tar.gz"
    sha256 "75e98c5f16b0f35b567856f597f06ff2270a374470a5c2392242528e3e3e42fc"
  end

  resource "idna" do
    url "https://files.pythonhosted.org/packages/cd/63/9496c57188a2ee585e0f1db071d75089a11e98aa86eb99d9d7618fc1edce/idna-3.18.tar.gz"
    sha256 "ffb385a7e039654cef1ab9ef32c6fafe283c0c0467bba1d9029738ce4a14a848"
  end

  resource "pyobjc-core" do
    url "https://files.pythonhosted.org/packages/2a/e8/a6cc12669211e7c9b29e8f26bf2159e67c7a73555dc229018abf46d8167a/pyobjc_core-12.2.tar.gz"
    sha256 "51d7de4cfa32f508c6a7aac31f131b12d5e196a8dcf588e6e8d7e6337224f66d"
  end

  resource "pyobjc-framework-Cocoa" do
    url "https://files.pythonhosted.org/packages/6d/cc/927169225e72bab9c9b44285656768fb75052a0bc85fdbca62740e1ca43c/pyobjc_framework_cocoa-12.2.tar.gz"
    sha256 "20b392e2b7241caad0538dfde12143343e5dfe48f72e7df660a7548e635903dc"
  end

  resource "pyobjc-framework-CoreText" do
    url "https://files.pythonhosted.org/packages/1f/b0/e7ef99240f853d4dddde82c9c0114cc525de7355661b2bf2d5e04cfb1582/pyobjc_framework_coretext-12.2.tar.gz"
    sha256 "82def2c281347e0677866315675124c84c36e9bc21651d62870cfdcecb7da34e"
  end

  resource "pyobjc-framework-Quartz" do
    url "https://files.pythonhosted.org/packages/91/a3/5ae4c90c13999b46315f549694f25c374c48a9f7ab18f98ace6e74f4a5c1/pyobjc_framework_quartz-12.2.tar.gz"
    sha256 "b343395d4790323b0376fe20c83ac468510ba19f65429323ca211708c939d107"
  end

  resource "PyYAML" do
    url "https://files.pythonhosted.org/packages/05/8e/961c0007c59b8dd7729d542c61a4d537767a59645b82a0b521206e1e25c2/pyyaml-6.0.3.tar.gz"
    sha256 "d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f"
  end

  resource "typing-extensions" do
    url "https://files.pythonhosted.org/packages/72/94/1a15dd82efb362ac84269196e94cf00f187f7ed21c242792a923cdb1c61f/typing_extensions-4.15.0.tar.gz"
    sha256 "0cea48d173cc12fa28ecabc3b837ea3cf6f38c6d1136f85cbaaf598984861466"
  end

  def install
    virtualenv_install_with_resources
  end

  def caveats
    <<~EOS
      L'agent FontSync est installé dans #{opt_bin}/fontsync-agent.

      Configurez l'URL du serveur et le token d'instance, puis enregistrez
      les LaunchAgents (sync + listen) :

        fontsync-agent setup

      La configuration vit dans ~/.fontsync/config.yaml (server.url + server.token).
      Pour retirer les LaunchAgents : `fontsync-agent teardown`.
    EOS
  end

  test do
    # La CLI doit répondre et exposer ses sous-commandes (sync/listen/setup/teardown).
    assert_match "fontsync-agent", shell_output("#{bin}/fontsync-agent --help 2>&1")
    # Import du paquet dans le venv embarqué (vérifie aussi que pyobjc s'est construit).
    system libexec/"bin/python", "-c", "import agent, httpx, yaml, CoreText"
  end
end
