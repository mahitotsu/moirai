package com.mahitotsu.moirai.graalvm;

import java.io.ByteArrayOutputStream;
import java.nio.charset.Charset;

import org.graalvm.polyglot.Context;
import org.graalvm.polyglot.HostAccess;
import org.graalvm.polyglot.io.IOAccess;

public class GraalvmScriptExecutor {

    public String evalPythonScript(final String script) {
        return this.evalScript("python", script);
    }

    public String evalScript(final String languageId, final String script) {

        final ByteArrayOutputStream outputStream = new ByteArrayOutputStream();

        Context.newBuilder(languageId)
                .allowHostAccess(HostAccess.ISOLATED)
                .allowIO(IOAccess.ALL)
                .out(outputStream)
                .build()
                .eval(languageId, script);

        return outputStream.toString(Charset.defaultCharset());
    }
}
