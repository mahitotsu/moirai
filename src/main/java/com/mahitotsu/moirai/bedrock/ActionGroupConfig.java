package com.mahitotsu.moirai.bedrock;

import java.util.Map;

import lombok.Builder;
import lombok.Data;
import software.amazon.awssdk.services.bedrockagentruntime.model.ParameterType;

@Builder
@Data
public class ActionGroupConfig {

    private String name;
    private String description;
    private Map<String, FunctionConfig> functions;

    @Builder
    @Data
    public static class FunctionConfig {
        private Map<String, ParameterConfig> parameters;
        private String description;
    }

    @Builder
    @Data
    public static class ParameterConfig {
        private ParameterType type;
        private String description;
        private boolean required;
    }
}
