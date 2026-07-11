// Passkey (WebAuthn) ceremonies: registration on the profile page, discoverable
// sign-in on the login page. GoTrue's passkeys API speaks base64url strings;
// navigator.credentials speaks ArrayBuffers — this file is the translation.

(() => {
	const b64urlToBuf = (s) => {
		const pad = "=".repeat((4 - (s.length % 4)) % 4);
		const raw = atob(s.replace(/-/g, "+").replace(/_/g, "/") + pad);
		return Uint8Array.from(raw, (c) => c.charCodeAt(0)).buffer;
	};

	const bufToB64url = (buf) =>
		btoa(String.fromCharCode(...new Uint8Array(buf)))
			.replace(/\+/g, "-")
			.replace(/\//g, "_")
			.replace(/=+$/, "");

	const post = async (url, body) => {
		const r = await fetch(url, {
			method: "POST",
			headers: { "Content-Type": "application/json", Accept: "application/json" },
			body: JSON.stringify(body || {}),
		});
		const data = await r.json().catch(() => ({}));
		if (!r.ok) throw new Error(data.detail || "Passkey operation failed.");
		return data;
	};

	// The fields common to a WebAuthn create()/get() result; `response` carries the
	// ceremony-specific parts (attestation vs assertion), already base64url-encoded.
	const encodeCredential = (c, response) => ({
		id: c.id,
		rawId: bufToB64url(c.rawId),
		type: c.type,
		clientExtensionResults: c.getClientExtensionResults(),
		response,
	});

	const showError = (scope, message) => {
		const el = scope.querySelector("[data-passkey-error]") || document.querySelector("[data-passkey-error]");
		if (el) {
			el.textContent = message;
			el.classList.remove("hidden");
		}
	};

	const register = async () => {
		const { challenge_id, options } = await post("/profile/passkeys/options");
		const pk = options.publicKey || options;
		pk.challenge = b64urlToBuf(pk.challenge);
		pk.user.id = b64urlToBuf(pk.user.id);
		for (const cred of pk.excludeCredentials || []) cred.id = b64urlToBuf(cred.id);
		const created = await navigator.credentials.create({ publicKey: pk });
		await post("/profile/passkeys/verify", {
			challenge_id,
			credential: encodeCredential(created, {
				clientDataJSON: bufToB64url(created.response.clientDataJSON),
				attestationObject: bufToB64url(created.response.attestationObject),
			}),
		});
		window.location.reload();
	};

	const signIn = async (next) => {
		const { challenge_id, options } = await post("/auth/passkeys/options");
		const pk = options.publicKey || options;
		pk.challenge = b64urlToBuf(pk.challenge);
		for (const cred of pk.allowCredentials || []) cred.id = b64urlToBuf(cred.id);
		const got = await navigator.credentials.get({ publicKey: pk });
		const data = await post("/auth/passkeys/verify", {
			challenge_id,
			next: next || "",
			credential: encodeCredential(got, {
				clientDataJSON: bufToB64url(got.response.clientDataJSON),
				authenticatorData: bufToB64url(got.response.authenticatorData),
				signature: bufToB64url(got.response.signature),
				userHandle: got.response.userHandle ? bufToB64url(got.response.userHandle) : "",
			}),
		});
		window.location.assign(data.redirect || "/profile");
	};

	document.addEventListener("click", (event) => {
		const registerBtn = event.target.closest("[data-passkey-register]");
		if (registerBtn) {
			register().catch((e) => showError(registerBtn.closest("section") || document.body, e.message));
			return;
		}
		const signinBtn = event.target.closest("[data-passkey-signin]");
		if (signinBtn) {
			signIn(signinBtn.dataset.next).catch((e) => showError(document.body, e.message));
		}
	});
})();
