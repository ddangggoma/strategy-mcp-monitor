// Ruling F19: an explicit manifest — tauri-build's default has only the Common-Controls v6 dependency.
// asInvoker: elevation happens only through an explicit `runas` relaunch (Y13), never by manifest.
const APP_MANIFEST: &str = r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <dependency>
    <dependentAssembly>
      <assemblyIdentity type="win32" name="Microsoft.Windows.Common-Controls" version="6.0.0.0"
        processorArchitecture="*" publicKeyToken="6595b64144ccf1df" language="*" />
    </dependentAssembly>
  </dependency>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="asInvoker" uiAccess="false" />
      </requestedPrivileges>
    </security>
  </trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}" />
    </application>
  </compatibility>
</assembly>
"#;

#[path = "src/payload_pack.rs"]
mod payload_pack;

use std::{env, fs, path::PathBuf};

/// Packs the payload (`MCPMON_PAYLOAD_DIR`, else the fixture) into `OUT_DIR` for `src/payload.rs` (Y14).
fn embed_payload() {
    println!("cargo:rerun-if-env-changed=MCPMON_PAYLOAD_DIR");
    let out = PathBuf::from(env::var("OUT_DIR").unwrap());
    let (dir, kind) = match env::var("MCPMON_PAYLOAD_DIR") {
        Ok(d) if !d.is_empty() => (PathBuf::from(d), "release"),
        _ => (PathBuf::from("tests/fixtures/payload"), "fixture"),
    };
    let packed = payload_pack::pack_dir(&dir, if kind == "release" { 19 } else { 3 })
        .unwrap_or_else(|e| panic!("payload {}: {e}", dir.display()));
    println!("cargo:rerun-if-changed={}", dir.display());
    for f in &packed.manifest.files {
        println!("cargo:rerun-if-changed={}", dir.join(&f.path).display());
    }
    if kind == "release" {
        payload_pack::check_release_layout(
            &packed.manifest,
            &env::var("CARGO_PKG_VERSION").unwrap(),
        )
        .unwrap_or_else(|e| panic!("release payload: {e}"));
    }
    fs::write(out.join("payload.tar.zst"), &packed.archive).unwrap();
    fs::write(out.join("payload.sha256"), &packed.sha256).unwrap();
    fs::write(
        out.join("payload-manifest.json"),
        serde_json::to_string(&packed.manifest).unwrap(),
    )
    .unwrap();
    fs::write(out.join("payload-kind.txt"), kind).unwrap();
}

fn main() {
    embed_payload();
    let windows = tauri_build::WindowsAttributes::new().app_manifest(APP_MANIFEST);
    tauri_build::try_build(tauri_build::Attributes::new().windows_attributes(windows))
        .expect("tauri-build failed");
}
