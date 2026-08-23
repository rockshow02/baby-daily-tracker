import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  isNotificationSupported, getNotificationPermission, requestNotificationPermission,
  isNotificationOptedIn, setNotificationOptedIn, hasNotifiedOccurrence,
  clearNotificationStateForUser, notifyDueOccurrence,
} from "./reminderNotifications";

class FakeNotification {
  constructor(title, options) {
    this.title = title;
    this.options = options;
    FakeNotification.instances.push(this);
  }
  close() {}
}
FakeNotification.permission = "default";
FakeNotification.requestPermission = vi.fn();
FakeNotification.instances = [];

const sensitiveReminder = { id: 1, reminder_type: "medication", title: "RAHASIA_Paracetamol_500mg" };
const occurrence = { occurrence_key: "2026-08-23" };

function installFakeNotification(permission = "default") {
  FakeNotification.permission = permission;
  FakeNotification.instances = [];
  FakeNotification.requestPermission = vi.fn().mockResolvedValue(permission);
  window.Notification = FakeNotification;
}

beforeEach(() => {
  localStorage.clear();
  installFakeNotification("default");
});

afterEach(() => {
  delete window.Notification;
  vi.restoreAllMocks();
});

describe("reminderNotifications — dukungan & izin", () => {
  it("isNotificationSupported false kalau Notification nggak ada di window", () => {
    delete window.Notification;
    expect(isNotificationSupported()).toBe(false);
    expect(getNotificationPermission()).toBe("unsupported");
  });

  it("getNotificationPermission mencerminkan Notification.permission apa adanya", () => {
    installFakeNotification("granted");
    expect(getNotificationPermission()).toBe("granted");
    installFakeNotification("denied");
    expect(getNotificationPermission()).toBe("denied");
    installFakeNotification("default");
    expect(getNotificationPermission()).toBe("default");
  });

  it("requestNotificationPermission balikin 'unsupported' kalau browser nggak dukung, TANPA throw", async () => {
    delete window.Notification;
    await expect(requestNotificationPermission()).resolves.toBe("unsupported");
  });

  it("requestNotificationPermission manggil Notification.requestPermission() beneran", async () => {
    installFakeNotification("default");
    const result = await requestNotificationPermission();
    expect(FakeNotification.requestPermission).toHaveBeenCalledTimes(1);
    expect(result).toBe("default");
  });
});

describe("reminderNotifications — opt-in per user", () => {
  it("opt-in nggak nyampur antar user", () => {
    setNotificationOptedIn(1, true);
    expect(isNotificationOptedIn(1)).toBe(true);
    expect(isNotificationOptedIn(2)).toBe(false);
  });

  it("mematikan opt-in menghapus preferensinya", () => {
    setNotificationOptedIn(1, true);
    setNotificationOptedIn(1, false);
    expect(isNotificationOptedIn(1)).toBe(false);
  });
});

describe("reminderNotifications — notifyDueOccurrence", () => {
  it("tidak menampilkan apa pun kalau izin belum granted", () => {
    installFakeNotification("default");
    setNotificationOptedIn(1, true);
    const shown = notifyDueOccurrence({ userId: 1, childId: 10, childName: "Dedek", reminder: sensitiveReminder, occurrence });
    expect(shown).toBe(false);
    expect(FakeNotification.instances).toHaveLength(0);
  });

  it("tidak menampilkan apa pun kalau user belum opt-in walau izin granted", () => {
    installFakeNotification("granted");
    const shown = notifyDueOccurrence({ userId: 1, childId: 10, childName: "Dedek", reminder: sensitiveReminder, occurrence });
    expect(shown).toBe(false);
    expect(FakeNotification.instances).toHaveLength(0);
  });

  it("menampilkan notifikasi kalau izin granted DAN opt-in", () => {
    installFakeNotification("granted");
    setNotificationOptedIn(1, true);
    const shown = notifyDueOccurrence({ userId: 1, childId: 10, childName: "Dedek", reminder: sensitiveReminder, occurrence });
    expect(shown).toBe(true);
    expect(FakeNotification.instances).toHaveLength(1);
  });

  it("teks notifikasi TIDAK PERNAH memuat title reminder yang sensitif", () => {
    installFakeNotification("granted");
    setNotificationOptedIn(1, true);
    notifyDueOccurrence({ userId: 1, childId: 10, childName: "Dedek", reminder: sensitiveReminder, occurrence });
    const body = FakeNotification.instances[0].options.body;
    expect(body).not.toContain("RAHASIA");
    expect(body).not.toContain("Paracetamol");
    expect(body).toMatch(/obat/i);
  });

  it("tidak menampilkan notifikasi dobel buat occurrence yang sama di browser yang sama", () => {
    installFakeNotification("granted");
    setNotificationOptedIn(1, true);
    notifyDueOccurrence({ userId: 1, childId: 10, childName: "Dedek", reminder: sensitiveReminder, occurrence });
    const shownAgain = notifyDueOccurrence({ userId: 1, childId: 10, childName: "Dedek", reminder: sensitiveReminder, occurrence });
    expect(shownAgain).toBe(false);
    expect(FakeNotification.instances).toHaveLength(1);
    expect(hasNotifiedOccurrence(1, 10, sensitiveReminder.id, occurrence.occurrence_key)).toBe(true);
  });

  it("occurrence yang BEDA (tanggal lain) tetap menampilkan notifikasi baru", () => {
    installFakeNotification("granted");
    setNotificationOptedIn(1, true);
    notifyDueOccurrence({ userId: 1, childId: 10, childName: "Dedek", reminder: sensitiveReminder, occurrence: { occurrence_key: "2026-08-23" } });
    const shown = notifyDueOccurrence({ userId: 1, childId: 10, childName: "Dedek", reminder: sensitiveReminder, occurrence: { occurrence_key: "2026-08-24" } });
    expect(shown).toBe(true);
    expect(FakeNotification.instances).toHaveLength(2);
  });

  it("hanya menyimpan occurrence_key non-sensitif di localStorage, bukan title", () => {
    installFakeNotification("granted");
    setNotificationOptedIn(1, true);
    notifyDueOccurrence({ userId: 1, childId: 10, childName: "Dedek", reminder: sensitiveReminder, occurrence });
    const rawKeys = Object.keys(localStorage).filter((k) => k.includes("notified_occurrences"));
    for (const key of rawKeys) {
      expect(localStorage.getItem(key)).not.toContain("RAHASIA");
      expect(localStorage.getItem(key)).not.toContain("Paracetamol");
    }
  });

  it("klik notifikasi memicu callback navigasi", () => {
    installFakeNotification("granted");
    setNotificationOptedIn(1, true);
    const onClickNavigate = vi.fn();
    notifyDueOccurrence({ userId: 1, childId: 10, childName: "Dedek", reminder: sensitiveReminder, occurrence, onClickNavigate });
    FakeNotification.instances[0].onclick();
    expect(onClickNavigate).toHaveBeenCalledTimes(1);
  });
});

describe("reminderNotifications — pembersihan logout", () => {
  it("clearNotificationStateForUser menghapus opt-in dan riwayat dedup, cuma buat user itu", () => {
    installFakeNotification("granted");
    setNotificationOptedIn(1, true);
    setNotificationOptedIn(2, true);
    notifyDueOccurrence({ userId: 1, childId: 10, childName: "Dedek", reminder: sensitiveReminder, occurrence });

    clearNotificationStateForUser(1);

    expect(isNotificationOptedIn(1)).toBe(false);
    expect(hasNotifiedOccurrence(1, 10, sensitiveReminder.id, occurrence.occurrence_key)).toBe(false);
    expect(isNotificationOptedIn(2)).toBe(true); // user lain nggak kesentuh
  });
});
