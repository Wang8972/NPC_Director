using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
var options=new JsonSerializerOptions{WriteIndented=true};
if(args.Length>=2&&args[0]=="syntax")
{
    var root=Path.GetFullPath(args[1]);var diagnostics=new List<object>();var errors=0;
    foreach(var file in Directory.GetFiles(Path.Combine(root,"Assets"),"*.cs",SearchOption.AllDirectories))
    {
        var syntax=CSharpSyntaxTree.ParseText(File.ReadAllText(file),new CSharpParseOptions(LanguageVersion.CSharp9,preprocessorSymbols:new[]{"UNITY_EDITOR"}),file);
        foreach(var d in syntax.GetDiagnostics().Where(d=>d.Severity==DiagnosticSeverity.Error))
        {errors++;diagnostics.Add(new{file=Path.GetRelativePath(root,file),message=d.ToString()});}
    }
    Console.WriteLine(JsonSerializer.Serialize(new{kind="Roslyn C# 9 syntax only; NOT Unity type/build validation",errors,diagnostics},options));
    return errors==0?0:1;
}
Console.Error.WriteLine("Usage: MockRenderer syntax <project>. Primitive geometry mocks were replaced by Blender asset previews.");
return 2;
