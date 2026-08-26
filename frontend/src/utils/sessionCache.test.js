import { beforeEach, describe, expect, it } from "vitest";
import {
  cacheUserProfile,
  getCachedUserProfile,
  clearCachedUserProfile,
  cacheChildren,
  getCachedChildren,
  clearCachedChildren,
  setCachedActiveChildId,
  getCachedActiveChildId,
  clearUserCache,
} from "./sessionCache";

beforeEach(() => {
  localStorage.clear();
});

describe("sessionCache — user profile", () => {
  it("caches and restores only the minimum profile fields", () => {
    cacheUserProfile({
      id: 5,
      name: "Ibu Test",
      email: "ibu@test.com",
      telegram_chat_id: "12345", // TIDAK boleh ikut ke-cache
      password_hash: "should-never-be-here",
    });

    const cached = getCachedUserProfile(5);
    expect(cached).toEqual({ id: 5, name: "Ibu Test", email: "ibu@test.com" });
    expect(cached.telegram_chat_id).toBeUndefined();
    expect(cached.password_hash).toBeUndefined();
  });

  it("10. is isolated by user id — reading a different id returns null", () => {
    cacheUserProfile({ id: 5, name: "Ibu Test", email: "ibu@test.com" });
    expect(getCachedUserProfile(6)).toBeNull();
  });

  it("returns null when nothing has ever been cached", () => {
    expect(getCachedUserProfile(1)).toBeNull();
  });

  it("returns null for malformed cached JSON instead of throwing", () => {
    localStorage.setItem("babytracker_cached_user_v1:5", "{not valid json");
    expect(getCachedUserProfile(5)).toBeNull();
  });

  it("clearCachedUserProfile removes only the given user's entry", () => {
    cacheUserProfile({ id: 5, name: "A", email: "a@test.com" });
    cacheUserProfile({ id: 6, name: "B", email: "b@test.com" });
    clearCachedUserProfile(5);
    expect(getCachedUserProfile(5)).toBeNull();
    expect(getCachedUserProfile(6)).toMatchObject({ id: 6 });
  });
});

describe("sessionCache — children list", () => {
  const rawChild = {
    id: 1,
    name: "Anak Satu",
    nickname: "Dedek",
    birth_date: "2024-01-01",
    gender: "L",
    birth_weight_kg: 3.2,
    birth_height_cm: 50,
    photo_filename: "photo.jpg",
    // campuran field yang TIDAK boleh ke-cache
    allergies: "kacang", // data medis/free-text
    notes: "catatan bebas dokter",
  };

  it("10. caches children after a successful online load, keeping only minimal fields", () => {
    cacheChildren(1, [rawChild]);
    const cached = getCachedChildren(1);
    expect(cached).toHaveLength(1);
    expect(cached[0]).toMatchObject({
      id: 1,
      name: "Anak Satu",
      nickname: "Dedek",
      birth_date: "2024-01-01",
      gender: "L",
      birth_weight_kg: 3.2,
      birth_height_cm: 50,
      photo_filename: "photo.jpg",
    });
    expect(cached[0].allergies).toBeUndefined();
    expect(cached[0].notes).toBeUndefined();
  });

  it("11. cached children are readable back after a simulated hard refresh (fresh read from storage)", () => {
    cacheChildren(7, [rawChild]);
    // simulasikan hard refresh: baca ulang dari 0, tanpa state in-memory apapun
    const restored = getCachedChildren(7);
    expect(restored[0].id).toBe(1);
  });

  it("12. the last active child id is stored and restored separately from the list", () => {
    cacheChildren(1, [rawChild, { ...rawChild, id: 2, name: "Anak Dua" }]);
    setCachedActiveChildId(1, 2);
    expect(getCachedActiveChildId(1)).toBe(2);
  });

  it("13. children cache is isolated by user id", () => {
    cacheChildren(1, [rawChild]);
    expect(getCachedChildren(2)).toEqual([]);
  });

  it("14. another account cannot see cached children from the previous account", () => {
    cacheChildren(1, [rawChild]);
    setCachedActiveChildId(1, 1);

    // user 2 login di perangkat yang sama — belum pernah punya cache sendiri
    expect(getCachedChildren(2)).toEqual([]);
    expect(getCachedActiveChildId(2)).toBeNull();

    // dan cache punya user 1 tetap utuh, nggak ketimpa/ke-merge
    expect(getCachedChildren(1)).toHaveLength(1);
  });

  it("returns an empty array (not null/throw) when nothing has ever been cached", () => {
    expect(getCachedChildren(99)).toEqual([]);
  });

  it("clearCachedChildren removes only the given user's entry", () => {
    cacheChildren(1, [rawChild]);
    cacheChildren(2, [rawChild]);
    clearCachedChildren(1);
    expect(getCachedChildren(1)).toEqual([]);
    expect(getCachedChildren(2)).toHaveLength(1);
  });
});

describe("sessionCache — clearUserCache", () => {
  it("wipes profile, children, and active-child-id for the given user only", () => {
    cacheUserProfile({ id: 1, name: "A", email: "a@test.com" });
    cacheChildren(1, [{ id: 10, name: "Anak" }]);
    setCachedActiveChildId(1, 10);

    cacheUserProfile({ id: 2, name: "B", email: "b@test.com" });
    cacheChildren(2, [{ id: 20, name: "Anak Lain" }]);
    setCachedActiveChildId(2, 20);

    clearUserCache(1);

    expect(getCachedUserProfile(1)).toBeNull();
    expect(getCachedChildren(1)).toEqual([]);
    expect(getCachedActiveChildId(1)).toBeNull();

    // user 2 nggak ikut kesentuh
    expect(getCachedUserProfile(2)).toMatchObject({ id: 2 });
    expect(getCachedChildren(2)).toHaveLength(1);
    expect(getCachedActiveChildId(2)).toBe(20);
  });
});
