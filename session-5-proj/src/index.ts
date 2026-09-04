import "dotenv/config";
import express from "express";
import { searchRouter } from "./routes/search.js";
import { statsRouter } from "./routes/stats.js";

const app = express();

app.use(searchRouter);
app.use(statsRouter);

const port = +(process.env.PORT ?? 3000);
app.listen(port, () => {
  console.log(`API listening on http://localhost:${port}`);
});
