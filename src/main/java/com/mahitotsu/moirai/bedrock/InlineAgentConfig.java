package com.mahitotsu.moirai.bedrock;

import java.util.Set;

import lombok.AccessLevel;
import lombok.Builder;
import lombok.Data;
import lombok.Setter;

@Builder
@Data
@Setter(AccessLevel.NONE)
public class InlineAgentConfig {
    private String name;
    private String instruction;
    private String foundationModel;
    private Set<String> actionGroupNames;
}

// "apac.amazon.nova-micro-v1:0"
