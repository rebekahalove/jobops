import "server-only";
import { readModelConnectorConfigFromEnv } from "@jobops/model-connector/server";
import type { ProfileIntakeApiRequest, ProfileIntakeOutput } from "./profile-intake-contract";
import { createProfileIntakeConnector, generateProfileIntakeOutput } from "./profile-intake-generator";
import { getJobOpsServerEnv } from "./server-env";

const MODEL_ENV_KEYS = [
  "JOBOPS_LLM_PROVIDER",
  "JOBOPS_DEFAULT_MODEL",
  "JOBOPS_CHEAP_MODEL",
  "GEMINI_API_KEY",
  "JOBOPS_PROFILE_INTAKE_SAVE_ARTIFACTS",
  "JOBOPS_PROFILE_INTAKE_SAVE_RAW_TEXT"
];

export async function runProfileIntakeExtraction(input: ProfileIntakeApiRequest): Promise<ProfileIntakeOutput> {
  const env = await getJobOpsServerEnv(MODEL_ENV_KEYS);
  const config = readModelConnectorConfigFromEnv(env);
  const connector = createProfileIntakeConnector(config);

  return generateProfileIntakeOutput(connector, input, {
    artifacts: {
      saveArtifacts: env.JOBOPS_PROFILE_INTAKE_SAVE_ARTIFACTS === "true",
      saveRawText: env.JOBOPS_PROFILE_INTAKE_SAVE_RAW_TEXT === "true"
    }
  });
}
