import { describe, expect, it } from "vitest";
import {
  RankStanding,
  RankTierError,
  RANK_TIERS,
} from "./rank";

describe("RankStanding", () => {
  it("한 단계 승급은 단계를 1 감소시킨다", () => {
    expect(new RankStanding("gold", 3).promoted()).toEqual(
      new RankStanding("gold", 2),
    );
  });

  it("단계 1에서 승급하면 상위 티어 5로 이동한다", () => {
    expect(new RankStanding("gold", 1).promoted()).toEqual(
      new RankStanding("platinum", 5),
    );
  });

  it("마스터 1은 승급해도 그대로 유지된다", () => {
    const top = new RankStanding("master", 1);
    expect(top.promoted()).toEqual(top);
  });

  it("한 단계 강등은 단계를 1 증가시킨다", () => {
    expect(new RankStanding("gold", 3).demoted()).toEqual(
      new RankStanding("gold", 4),
    );
  });

  it("단계 5에서 강등하면 하위 티어 1로 이동한다", () => {
    expect(new RankStanding("bronze", 5).demoted()).toEqual(
      new RankStanding("rookie", 1),
    );
  });

  it("루키 5는 강등해도 그대로 유지된다", () => {
    const bottom = new RankStanding("rookie", 5);
    expect(bottom.demoted()).toEqual(bottom);
  });

  it("알 수 없는 티어는 오류를 던진다", () => {
    expect(() => new RankStanding("challenger", 1)).toThrow(RankTierError);
  });

  it("범위 밖 단계는 오류를 던진다", () => {
    expect(() => new RankStanding("gold", 0)).toThrow(RankTierError);
    expect(() => new RankStanding("gold", 6)).toThrow(RankTierError);
  });

  it("티어 순서는 루키부터 마스터까지다", () => {
    expect(RANK_TIERS.map((tier) => tier.value)).toEqual([
      "rookie",
      "bronze",
      "silver",
      "gold",
      "platinum",
      "diamond",
      "master",
    ]);
  });
});
