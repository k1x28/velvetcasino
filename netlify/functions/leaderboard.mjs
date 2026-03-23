import { getStore } from "@netlify/blobs";

export default async (req) => {
  const store = getStore({ name: "leaderboard", consistency: "strong" });

  if (req.method === "GET") {
    const { blobs } = await store.list();
    const users = [];
    for (const blob of blobs) {
      const data = await store.get(blob.key, { type: "json" });
      if (data) users.push(data);
    }
    users.sort((a, b) => b.balance - a.balance);
    return Response.json(users.slice(0, 25));
  }

  if (req.method === "POST") {
    const body = await req.json();
    const { username, balance, stats, avatar } = body;
    if (!username) {
      return Response.json({ error: "Username required" }, { status: 400 });
    }
    const entry = {
      username,
      balance: parseFloat(balance) || 0,
      stats: {
        wins: stats?.wins || 0,
        losses: stats?.losses || 0,
        total_wagered: stats?.total_wagered || 0,
        biggest_win: stats?.biggest_win || 0,
      },
      avatar: avatar || "",
      updated: Date.now(),
    };
    await store.setJSON(`player:${username}`, entry);
    return Response.json({ ok: true });
  }

  return Response.json({ error: "Method not allowed" }, { status: 405 });
};

export const config = {
  path: "/api/leaderboard",
};
