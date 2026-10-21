"""Izbor modela.

Aplikacija je jednom vec stala zato sto je naziv modela bio tvrdo upisan i
Google ga je penzionisao. Ovi testovi pinuju ono sto to sprecava: da se bira iz
spiska koji vrati kljuc, i da izbor radi i kad nijedan poznat naziv ne postoji.
"""

import json
from unittest import mock

from app import db
from app.ai import gemini, models
from app.services import ai_models, settings_store

from .base import AppTestCase

# Spisak kakav Gemini stvarno vraca u avgustu 2026.
LIVE = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.1-pro-preview",
    "gemini-3.1-flash-tts-preview",
    "gemini-3.1-flash-image",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "text-embedding-004",
]

ONLY_OLD = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]


class DefaultsTests(AppTestCase):
    def test_no_tier_defaults_to_a_retired_family(self):
        """Ovo je bas kvar koji je prijavljen: aplikacija je forsirala 2.5."""
        for tier in models.TIERS:
            chosen = models.default_for(tier)
            self.assertFalse(models.is_retired(chosen), f"{tier} podrazumevano nudi {chosen}")

    def test_every_tier_has_a_preference_list(self):
        for tier in models.TIERS:
            self.assertTrue(models.preferred(tier), tier)

    def test_old_names_are_kept_as_last_resort(self):
        """Poneki kljuc jos ima pristup samo starim modelima - ne izbacujemo ih."""
        joined = sum((models.preferred(tier) for tier in models.TIERS), [])
        self.assertTrue(any(models.is_retired(name) for name in joined))


class ResolveTests(AppTestCase):
    def test_picks_the_newest_the_key_actually_has(self):
        """Najnoviji stabilan, ne prvi iz liste zelja - lista zelja je drzala
        3.6 iako je kljuc imao 3.7."""
        resolved = models.resolve_all(LIVE)
        self.assertEqual(resolved["standard"], "gemini-3.7-flash")
        self.assertEqual(resolved["fast"], "gemini-3.5-flash-lite")
        self.assertEqual(resolved["strong"], "gemini-3.7-flash")
        self.assertEqual(resolved["tts"], "gemini-3.1-flash-tts-preview")

    def test_falls_back_to_old_models_when_that_is_all_there_is(self):
        resolved = models.resolve_all(ONLY_OLD)
        self.assertEqual(resolved["standard"], "gemini-2.5-flash")
        self.assertIsNone(resolved["tts"], "medju starima nema TTS modela")

    def test_unknown_future_family_is_ranked_by_shape(self):
        """Deo zbog kog ovo prezivljava sledece preimenovanje: nijedan naziv
        nije u listi zelja, pa se bira po obliku i verziji."""
        future = [
            "gemini-4.2-flash", "gemini-4.2-flash-lite", "gemini-4.2-pro",
            "gemini-4.0-pro", "gemini-4.0-flash-tts-preview", "gemini-4.2-flash-image",
        ]
        resolved = models.resolve_all(future)
        self.assertEqual(resolved["fast"], "gemini-4.2-flash-lite")
        self.assertEqual(resolved["standard"], "gemini-4.2-flash")
        self.assertEqual(resolved["strong"], "gemini-4.2-pro")
        self.assertEqual(resolved["tts"], "gemini-4.0-flash-tts-preview")

    def test_higher_version_wins_within_the_same_shape(self):
        self.assertEqual(models.resolve("strong", ["gemini-4.0-pro", "gemini-4.2-pro"]),
                         "gemini-4.2-pro")

    def test_non_text_models_never_reach_a_text_tier(self):
        noise = ["gemini-4.2-flash-image", "text-embedding-004", "veo-3", "imagen-4",
                 "gemini-4.2-flash-native-audio", "gemini-4.2-flash"]
        for tier in ("fast", "standard", "strong"):
            chosen = models.resolve(tier, noise)
            self.assertEqual(chosen, "gemini-4.2-flash", f"{tier} izabrao {chosen}")

    def test_tts_tier_only_picks_tts_models(self):
        self.assertEqual(models.resolve("tts", LIVE), "gemini-3.1-flash-tts-preview")
        self.assertIsNone(models.resolve("tts", ["gemini-4.2-flash", "gemini-4.2-pro"]))

    def test_empty_list_resolves_to_nothing(self):
        for tier in models.TIERS:
            self.assertIsNone(models.resolve(tier, []), tier)

    def test_retirement_check(self):
        self.assertTrue(models.is_retired("gemini-2.5-pro"))
        self.assertTrue(models.is_retired("gemini-2.0-flash"))
        self.assertFalse(models.is_retired("gemini-3.6-flash"))
        self.assertFalse(models.is_retired("nesto-bez-verzije"))


class ForTierTests(AppTestCase):
    def _remember(self, names):
        settings_store.set_value(ai_models.AVAILABLE_KEY, json.dumps(names))

    def test_without_a_known_list_it_uses_the_preference(self):
        self.assertEqual(ai_models.for_tier("standard"), models.default_for("standard"))

    def test_with_a_list_it_resolves_against_it(self):
        self._remember(ONLY_OLD)
        self.assertEqual(ai_models.for_tier("standard"), "gemini-2.5-flash")

    def test_manual_choice_wins(self):
        self._remember(LIVE)
        settings_store.set_value("model_standard", "gemini-3.5-flash")
        self.assertEqual(ai_models.for_tier("standard"), "gemini-3.5-flash")

    def test_auto_keyword_is_treated_as_automatic(self):
        self._remember(LIVE)
        settings_store.set_value("model_standard", "auto")
        self.assertEqual(ai_models.for_tier("standard"), "gemini-3.7-flash")


class RefreshTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.calls = []
        self._real_probe = gemini.probe
        gemini.probe = self._fake_probe

    def tearDown(self):
        gemini.probe = self._real_probe
        super().tearDown()

    def _fake_probe(self, api_key):
        """Stoji na mestu mreznog poziva. Oblik je isti kao sto vraca pravi
        `gemini.probe` - to je pinovano u ProbeShapeTests."""
        self.calls.append(api_key)
        listing = getattr(self, "listing", LIVE)
        return {"ok": True, "models": [{"name": name} for name in listing], "count": len(listing)}

    def test_refresh_stores_the_list_and_resolves_tiers(self):
        report = ai_models.refresh("kljuc")
        self.assertTrue(report["ok"])
        self.assertEqual(ai_models.available(), LIVE)
        self.assertEqual(report["resolved"]["standard"], "gemini-3.7-flash")
        self.assertEqual(ai_models.for_tier("tts"), "gemini-3.1-flash-tts-preview")

    def test_refresh_never_writes_the_automatic_choice(self):
        """Kvar zbog kog su korisnici menjali model rucno: osvezavanje je
        upisivalo razreseni naziv u model_*, pa je "Automatski" od tada bio
        rucni izbor i nova generacija se nikad nije koristila."""
        ai_models.refresh("kljuc")
        for tier, setting in ai_models.SETTING_BY_TIER.items():
            self.assertEqual(settings_store.get(setting), "", f"{tier} je upisan kao rucni izbor")
        found = {item["tier"]: item for item in ai_models.status()["tiers"]}
        self.assertFalse(found["standard"]["manual"])

    def test_new_generation_is_used_as_soon_as_the_list_shows_it(self):
        ai_models.refresh("kljuc")
        self.listing = ["gemini-4.0-flash", "gemini-4.0-flash-lite", "gemini-4.0-pro", *LIVE]
        report = ai_models.refresh("kljuc")

        self.assertEqual(ai_models.for_tier("standard"), "gemini-4.0-flash")
        self.assertEqual(ai_models.for_tier("fast"), "gemini-4.0-flash-lite")
        self.assertEqual(ai_models.for_tier("strong"), "gemini-4.0-pro")
        changed = {item["tier"]: item for item in report["changes"]}
        self.assertEqual(changed["standard"], {"tier": "standard", "from": "gemini-3.7-flash",
                                               "to": "gemini-4.0-flash"})

    def test_retired_choice_is_replaced_and_reported(self):
        """2.5 je jos na spisku, ali se gasi. Postovati taj izbor do trenutka kad
        poziv pukne znaci pustiti korisnika da to otkrije usred ucenja."""
        settings_store.set_value("model_standard", "gemini-2.5-flash")
        report = ai_models.refresh("kljuc")

        changed = {item["tier"]: item for item in report["changes"]}
        self.assertIn("standard", changed)
        self.assertEqual(changed["standard"]["from"], "gemini-2.5-flash")
        self.assertEqual(changed["standard"]["to"], "gemini-3.7-flash")
        self.assertEqual(settings_store.get("model_standard"), "", "vraca se na automatski")

    def test_current_manual_choice_is_left_alone(self):
        """A izbor koji je i dalje aktuelan se NE dira - inace bi ova zamena
        gazila svaku korisnikovu odluku."""
        settings_store.set_value("model_standard", "gemini-3.5-flash")
        report = ai_models.refresh("kljuc")
        self.assertEqual(settings_store.get("model_standard"), "gemini-3.5-flash")
        self.assertNotIn("standard", {item["tier"] for item in report["changes"]})

    def test_choice_that_vanished_is_replaced(self):
        settings_store.set_value("model_standard", "gemini-1.0-izmisljeni")
        ai_models.refresh("kljuc")
        self.assertEqual(settings_store.get("model_standard"), "")
        self.assertEqual(ai_models.for_tier("standard"), "gemini-3.7-flash")

    def test_without_a_key_it_says_so_and_calls_nothing(self):
        report = ai_models.refresh("")
        self.assertFalse(report["ok"])
        self.assertEqual(self.calls, [])

    def test_status_flags_a_retired_choice(self):
        settings_store.set_value(ai_models.AVAILABLE_KEY, json.dumps(ONLY_OLD))
        settings_store.set_value("model_standard", "gemini-2.5-flash")
        found = {item["tier"]: item for item in ai_models.status()["tiers"]}
        self.assertTrue(found["standard"]["retired"])
        self.assertFalse(found["standard"]["missing"])

    def test_status_flags_a_choice_the_key_does_not_have(self):
        settings_store.set_value(ai_models.AVAILABLE_KEY, json.dumps(LIVE))
        settings_store.set_value("model_standard", "gemini-9.9-nepostojeci")
        found = {item["tier"]: item for item in ai_models.status()["tiers"]}
        self.assertTrue(found["standard"]["missing"])


class ProbeShapeTests(AppTestCase):
    def test_real_probe_returns_the_shape_the_stub_imitates(self):
        """Bez ovoga bi se stub iz RefreshTests i kod slagali samo medjusobno.

        Mreza je u testovima blokirana, pa pravi poziv padne - ali oblik
        NEUSPEHA je isto deo ugovora i `refresh` se na njega oslanja.
        """
        result = gemini.probe("lazan-kljuc")
        self.assertIn("ok", result)
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

        report = ai_models.refresh("lazan-kljuc")
        self.assertFalse(report["ok"])
        self.assertIn("error", report)


class AutoRemapTests(AppTestCase):
    def test_network_failure_is_not_mistaken_for_a_retired_model(self):
        """Mreza je blokirana u testovima; ta greska NE sme da pokrene zamenu
        modela - inace bi svaki ispad interneta prepravljao podesavanja."""
        settings_store.set_value("gemini_api_key", "lazan-kljuc")
        settings_store.set_value("model_standard", "gemini-3.6-flash")

        with self.assertRaises(gemini.AiError):
            ai_models.generate("standard", "pitanje")

        self.assertEqual(settings_store.get("model_standard"), "gemini-3.6-flash")

    def test_missing_model_errors_are_recognised(self):
        for message in ("Model not found", "is not supported", "has been deprecated"):
            error = gemini.AiError(message, status=404)
            self.assertTrue(ai_models._looks_like_missing_model(error), message)

    def test_other_errors_are_not(self):
        for status, message in ((429, "Quota exceeded"), (500, "Internal"), (0, "blokirani")):
            error = gemini.AiError(message, status=status)
            self.assertFalse(ai_models._looks_like_missing_model(error), message)


class ThinkingTests(AppTestCase):
    """Ocenjivanje otvorenog odgovora je trajalo i po dva minuta: model je
    podrazumevano razmisljao, a cetiri pokusaja sa timeout-om od 300 s nisu
    imala gornju granicu koju student moze da saceka. Ovo pinuje da se
    razmisljanje stisava po pravom polju za svaku generaciju."""

    def test_new_family_uses_thinking_level(self):
        self.assertEqual(models.thinking_config("gemini-3.6-flash", "low"), {"thinkingLevel": "low"})

    def test_old_flash_turns_thinking_off(self):
        self.assertEqual(models.thinking_config("gemini-2.5-flash", "low"), {"thinkingBudget": 0})

    def test_old_pro_gets_the_minimum_it_accepts(self):
        self.assertEqual(models.thinking_config("gemini-2.5-pro", "low"), {"thinkingBudget": 128})

    def test_default_leaves_the_model_alone(self):
        self.assertIsNone(models.thinking_config("gemini-3.6-flash", ""))
        self.assertIsNone(models.thinking_config("nepoznat-model", "low"))


class GenerateRequestTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.sent = []
        self._real_post = gemini._post_json
        gemini._post_json = self._fake_post
        self.reject_thinking = False

    def tearDown(self):
        gemini._post_json = self._real_post
        super().tearDown()

    def _fake_post(self, url, api_key, body, timeout_s, max_attempts):
        config = json.loads(json.dumps(body["generationConfig"]))
        self.sent.append({"config": config, "timeout_s": timeout_s, "max_attempts": max_attempts})
        if self.reject_thinking and "thinkingConfig" in config:
            raise gemini.AiError("Unknown field thinkingConfig.thinkingLevel", status=400)
        return {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}

    def test_interactive_call_sends_limits_and_low_thinking(self):
        gemini.generate("k", "gemini-3.6-flash", "p", thinking="low", timeout_s=30, max_attempts=2)
        self.assertEqual(self.sent[0]["config"]["thinkingConfig"], {"thinkingLevel": "low"})
        self.assertEqual((self.sent[0]["timeout_s"], self.sent[0]["max_attempts"]), (30, 2))

    def test_background_call_is_unchanged(self):
        gemini.generate("k", "gemini-3.6-flash", "p")
        self.assertNotIn("thinkingConfig", self.sent[0]["config"])
        self.assertEqual(self.sent[0]["max_attempts"], gemini.MAX_ATTEMPTS)

    def test_model_that_rejects_thinking_is_asked_again_without_it(self):
        self.reject_thinking = True
        result = gemini.generate("k", "gemini-3.6-flash", "p", thinking="low")
        self.assertEqual(len(self.sent), 2)
        self.assertNotIn("thinkingConfig", self.sent[1]["config"])
        self.assertEqual(result["text"], "{}")


# --------------------------------------------------------------------------
# "Uvek najnoviji, bez klika": korisnik ne sme da mora da menja model rucno.


class NewestRankingTests(AppTestCase):
    def test_stable_beats_a_newer_preview(self):
        """Nov preview obicno nema besplatnu kvotu - stabilan radi svima."""
        self.assertEqual(
            models.resolve("standard", ["gemini-3.7-flash", "gemini-4.0-flash-preview"]),
            "gemini-3.7-flash",
        )

    def test_preview_is_used_when_nothing_stable_fits(self):
        self.assertEqual(
            models.resolve("standard", ["gemini-4.0-flash-preview", "gemini-3.9-flash-preview"]),
            "gemini-4.0-flash-preview",
        )

    def test_newest_generation_beats_an_older_pro(self):
        """Za najjaci nivo: 4.x flash pre 3.x pro - nova generacija je jaca."""
        self.assertEqual(models.resolve("strong", ["gemini-3.7-pro", "gemini-4.0-flash"]),
                         "gemini-4.0-flash")

    def test_old_pro_never_beats_a_new_flash(self):
        self.assertEqual(models.resolve("strong", ["gemini-2.5-pro", "gemini-3.6-flash"]),
                         "gemini-3.6-flash")

    def test_alias_without_a_version_comes_last(self):
        """`gemini-flash-latest` ne kaze verziju, pa ni koje polje za
        razmisljanje prima - i moze da pokazuje na preview."""
        self.assertEqual(models.resolve("standard", ["gemini-flash-latest", "gemini-3.6-flash"]),
                         "gemini-3.6-flash")

    def test_experimental_counts_as_unstable(self):
        self.assertTrue(models.is_preview("gemini-4.0-flash-exp"))
        self.assertTrue(models.is_preview("gemini-4.0-flash-preview-05-20"))
        self.assertFalse(models.is_preview("gemini-4.0-flash"))
        self.assertFalse(models.is_preview("gemini-4.0-flash-express"))

    def test_skipped_model_gives_way_to_the_next_newest(self):
        self.assertEqual(models.resolve("standard", LIVE, skip={"gemini-3.7-flash"}),
                         "gemini-3.6-flash")

    def test_specialised_models_never_reach_a_text_tier(self):
        noise = ["gemini-4.5-computer-use-preview", "gemini-robotics-er-4.5", "gemini-3.6-flash"]
        self.assertEqual(models.resolve("strong", noise), "gemini-3.6-flash")


class StaleRefreshTests(AppTestCase):
    def setUp(self):
        super().setUp()
        settings_store.set_value("gemini_api_key", "kljuc")
        ai_models._last_refresh_attempt = 0.0
        self.probes = []

    def _probe(self, api_key):
        self.probes.append(api_key)
        return {"ok": True, "models": [{"name": "gemini-4.0-flash"}, *({"name": n} for n in LIVE)]}

    def _call(self):
        reply = {"text": "{}", "model": "x"}
        with mock.patch.object(gemini, "probe", side_effect=self._probe), \
                mock.patch.object(gemini, "generate", return_value=reply) as generate:
            ai_models.generate("standard", "pitanje")
        return generate.call_args.args[1]

    def test_list_older_than_a_day_is_refreshed_before_the_call(self):
        settings_store.set_value(ai_models.AVAILABLE_KEY, json.dumps(LIVE))
        settings_store.set_value(ai_models.CHECKED_KEY,
                                 db.scalar("SELECT datetime('now', '-2 days')"))
        self.assertEqual(self._call(), "gemini-4.0-flash", "nova generacija bez ijednog klika")
        self.assertEqual(len(self.probes), 1)

    def test_fresh_list_is_not_asked_again(self):
        settings_store.set_value(ai_models.AVAILABLE_KEY, json.dumps(LIVE))
        settings_store.set_value(ai_models.CHECKED_KEY, db.scalar("SELECT datetime('now')"))
        self.assertEqual(self._call(), "gemini-3.7-flash")
        self.assertEqual(self.probes, [])

    def test_failed_refresh_is_not_retried_before_every_call(self):
        """Bez mreze ne sme svaki poziv da plati jos jedan neuspeo upit spiska."""
        failing = mock.patch.object(gemini, "probe", return_value={"ok": False, "error": "mreza"})
        with failing as probe:
            ai_models.refresh_if_stale()
            ai_models.refresh_if_stale()
        self.assertEqual(probe.call_count, 1)


class SwitchingTests(AppTestCase):
    """Model koji ne radi sa ovim kljucem se preskace - u istom pozivu."""

    def setUp(self):
        super().setUp()
        settings_store.set_value("gemini_api_key", "kljuc")
        settings_store.set_value(ai_models.AVAILABLE_KEY, json.dumps(LIVE))
        settings_store.set_value(ai_models.CHECKED_KEY, db.scalar("SELECT datetime('now')"))
        self.tried = []

    def _generate(self, failures):
        def fake(api_key, model, prompt, **kwargs):
            self.tried.append(model)
            if model in failures:
                raise failures[model]
            return {"text": "{}", "model": model}
        return mock.patch.object(gemini, "generate", side_effect=fake)

    def test_model_without_free_quota_is_skipped_and_remembered(self):
        no_quota = gemini._http_error(
            429, "Quota exceeded for metric: generate_content_free_tier_requests, limit: 0, "
                 "model: gemini-3.7-flash")
        with self._generate({"gemini-3.7-flash": no_quota}):
            result = ai_models.generate("standard", "pitanje")
            self.assertEqual(result["model_switched"],
                             {"from": "gemini-3.7-flash", "to": "gemini-3.6-flash"})
            self.assertIn("gemini-3.7-flash", ai_models.unusable())

            self.tried.clear()
            ai_models.generate("standard", "pitanje")
        self.assertEqual(self.tried, ["gemini-3.6-flash"], "drugi put se ne trosi poziv na njega")

    def test_caller_that_resolved_early_does_not_hit_a_known_dead_model(self):
        """Generisanje razresi model na pocetku pa ga salje za svaki komad."""
        ai_models.mark_unusable("gemini-3.7-flash")
        with self._generate({}):
            ai_models.generate("standard", "pitanje", model="gemini-3.7-flash")
        self.assertEqual(self.tried, ["gemini-3.6-flash"])

    def test_used_up_quota_switches_for_this_call_only(self):
        """Svaki model ima svoju kvotu; potrosena kvota nije trajna osobina."""
        busy = gemini.AiError("Prešao si besplatnu kvotu za sada.", status=429, retryable=True)
        with self._generate({"gemini-3.7-flash": busy}):
            result = ai_models.generate("standard", "pitanje")
        self.assertEqual(result["model_switched"]["to"], "gemini-3.6-flash")
        self.assertNotIn("gemini-3.7-flash", ai_models.unusable())

    def test_manual_choice_is_not_switched_on_quota(self):
        settings_store.set_value("model_standard", "gemini-3.5-flash")
        busy = gemini.AiError("Prešao si besplatnu kvotu za sada.", status=429)
        with self._generate({"gemini-3.5-flash": busy}):
            with self.assertRaises(gemini.AiError):
                ai_models.generate("standard", "pitanje")
        self.assertEqual(self.tried, ["gemini-3.5-flash"])

    def test_switching_stops_after_a_few_models(self):
        """Kad svi padaju, kriv je kljuc ili mreza - dalje probanje samo trosi kvotu."""
        busy = gemini.AiError("Prešao si besplatnu kvotu za sada.", status=429)
        with self._generate({name: busy for name in LIVE}):
            with self.assertRaises(gemini.AiError):
                ai_models.generate("standard", "pitanje")
        self.assertEqual(len(self.tried), ai_models.MAX_SWITCHES + 1)

    def test_request_errors_do_not_switch_models(self):
        bad = gemini.AiError("Zahtev nije prihvaćen.", status=400)
        with self._generate({"gemini-3.7-flash": bad}):
            with self.assertRaises(gemini.AiError):
                ai_models.generate("standard", "pitanje")
        self.assertEqual(self.tried, ["gemini-3.7-flash"])

    def test_remembered_model_is_forgotten_after_a_week(self):
        """Google ume da vrati besplatnu kvotu - zabrana nije zauvek."""
        old = db.scalar("SELECT datetime('now', ?)", (f"-{ai_models.UNUSABLE_DAYS + 1} days",))
        settings_store.set_value(ai_models.UNUSABLE_KEY, {"gemini-3.7-flash": old})
        self.assertEqual(ai_models.unusable(), {})
        self.assertEqual(ai_models.for_tier("standard"), "gemini-3.7-flash")


class NoFreeQuotaErrorTests(AppTestCase):
    def test_limit_zero_is_not_retried_and_says_what_it_means(self):
        error = gemini._http_error(429, "Quota exceeded for metric: x, limit: 0, model: y")
        self.assertTrue(gemini.is_no_free_quota(error))
        self.assertFalse(error.retryable, "cekanje ne pomaze - pomaze drugi model")
        self.assertIn("nema besplatnu kvotu", error.message)

    def test_ordinary_quota_is_still_retried(self):
        error = gemini._http_error(429, "Quota exceeded for metric: x, limit: 15, model: y")
        self.assertFalse(gemini.is_no_free_quota(error))
        self.assertTrue(error.retryable)


class ResetWrittenChoiceMigrationTests(AppTestCase):
    def test_choices_written_by_the_old_refresh_go_back_to_automatic(self):
        """Stari `refresh` je upisivao automatski izbor; migracija ga brise."""
        settings_store.set_value("model_standard", "gemini-3.6-flash")
        settings_store.set_value("gemini_api_key", "kljuc")
        reset = next(sql for sql in reversed(db.MIGRATIONS) if "model_standard" in sql)
        for statement in db.statements(reset):
            db.execute(statement)

        self.assertEqual(settings_store.get("model_standard"), "")
        self.assertEqual(settings_store.get("gemini_api_key"), "kljuc", "ostala podesavanja ostaju")
